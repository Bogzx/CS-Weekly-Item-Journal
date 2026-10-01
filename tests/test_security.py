"""Tests for request-handling hardening in app.py."""

import base64
import io
import os
import subprocess
import sys
import uuid

import pytest
from PIL import Image


def png_data_url(size=(8, 8), subtype='png', fmt='PNG'):
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 100, 0)).save(buf, format=fmt)
    return f"data:image/{subtype};base64," + base64.b64encode(buf.getvalue()).decode()


class TestDecodePastedImage:
    def test_png_data_url(self, appmod):
        ext, data = appmod.decode_pasted_image(png_data_url())

        assert ext == 'png'
        assert data.startswith(b'\x89PNG')

    def test_jpeg_maps_to_jpg(self, appmod):
        ext, _ = appmod.decode_pasted_image(png_data_url(subtype='jpeg', fmt='JPEG'))

        assert ext == 'jpg'

    def test_gif_is_stored_as_png_because_opencv_cannot_read_gif(self, appmod):
        ext, _ = appmod.decode_pasted_image(png_data_url(subtype='gif', fmt='GIF'))

        assert ext == 'png'

    def test_bare_base64_defaults_to_png(self, appmod):
        ext, _ = appmod.decode_pasted_image(png_data_url().split(',', 1)[1])

        assert ext == 'png'

    @pytest.mark.parametrize('header', [
        'data:image/..\\..\\app.py;base64',   # path traversal via the subtype (Windows)
        'data:image/py;base64',               # attacker-chosen extension
        'data:image/svg+xml;base64',          # not a raster format we can process
        'data:text/html;base64',
        'data:image/png',                     # not base64
    ])
    def test_rejects_headers_that_would_choose_the_file_name(self, appmod, header):
        payload = png_data_url().split(',', 1)[1]

        with pytest.raises(ValueError):
            appmod.decode_pasted_image(f'{header},{payload}')

    def test_rejects_bytes_that_are_not_an_image(self, appmod):
        """These used to be written to disk verbatim when PIL failed."""
        payload = base64.b64encode(b'import os; os.system("calc")').decode()

        with pytest.raises(ValueError):
            appmod.decode_pasted_image(f'data:image/png;base64,{payload}')

    def test_rejects_invalid_base64(self, appmod):
        with pytest.raises(ValueError):
            appmod.decode_pasted_image('data:image/png;base64,@@@not-base64@@@')

    def test_rejects_empty(self, appmod):
        with pytest.raises(ValueError):
            appmod.decode_pasted_image('')


class TestSavePastedImage:
    def test_downscales_large_images_preserving_aspect(self, appmod, tmp_path):
        _, data = appmod.decode_pasted_image(png_data_url(size=(4096, 1024)))
        out = str(tmp_path / 'x.png')

        appmod.save_pasted_image(data, out)

        with Image.open(out) as img:
            assert img.size == (2048, 512)

    def test_rgba_saved_as_jpg(self, appmod, tmp_path):
        buf = io.BytesIO()
        Image.new('RGBA', (4, 4)).save(buf, format='PNG')
        out = str(tmp_path / 'x.jpg')

        appmod.save_pasted_image(buf.getvalue(), out)

        with Image.open(out) as img:
            assert img.format == 'JPEG'


    def test_cmyk_jpeg_pasted_as_png_is_saved(self, appmod, tmp_path):
        buf = io.BytesIO()
        Image.new('CMYK', (8, 8)).save(buf, format='JPEG')
        ext, data = appmod.decode_pasted_image(
            'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode())
        target = tmp_path / f'shot.{ext}'

        appmod.save_pasted_image(data, str(target))

        with Image.open(target) as img:
            assert img.format == 'PNG'


class TestIsSafeRedirect:
    @pytest.mark.parametrize('target', ['/', '/history', '/profile?tab=1'])
    def test_local_paths_allowed(self, appmod, target):
        assert appmod.is_safe_redirect(target)

    @pytest.mark.parametrize('target', [
        None, '', 'history', 'https://evil.example/', '//evil.example/',
        '/\\evil.example', '///evil.example',
    ])
    def test_other_hosts_rejected(self, appmod, target):
        assert not appmod.is_safe_redirect(target)


class TestResolveSecretKey:
    def test_real_key_is_kept(self, appmod):
        assert appmod.resolve_secret_key('a' * 64) == 'a' * 64

    @pytest.mark.parametrize('raw', [None, '', 'CHANGE_ME_RUN_THE_COMMAND_ABOVE'])
    def test_placeholder_or_missing_gets_a_random_key(self, appmod, raw):
        key = appmod.resolve_secret_key(raw)

        assert isinstance(key, bytes) and len(key) == 24


class TestRoutes:
    def test_login_does_not_redirect_off_site(self, client):
        name = f'user_{uuid.uuid4().hex[:8]}'
        client.post('/register', data={
            'username': name, 'email': f'{name}@example.com',
            'password': 'pw', 'confirm_password': 'pw',
        })

        resp = client.post('/login?next=//evil.example/', data={'username': name, 'password': 'pw'})

        assert resp.status_code == 302
        assert 'evil.example' not in resp.headers['Location']

    def test_login_honours_local_next(self, client):
        name = f'user_{uuid.uuid4().hex[:8]}'
        client.post('/register', data={
            'username': name, 'email': f'{name}@example.com',
            'password': 'pw', 'confirm_password': 'pw',
        })

        resp = client.post('/login?next=/history', data={'username': name, 'password': 'pw'})

        assert resp.headers['Location'].endswith('/history')

    def test_crafted_paste_is_rejected_and_nothing_is_written(self, appmod, logged_in):
        upload_dir = appmod.app.config['UPLOAD_FOLDER']
        before = set(os.listdir(upload_dir))
        payload = base64.b64encode(b'not an image').decode()

        resp = logged_in.post('/upload', data={'image_data': f'data:image/py;base64,{payload}'})

        assert resp.status_code == 400
        assert set(os.listdir(upload_dir)) == before

    def test_valid_paste_reaches_the_pipeline(self, appmod, logged_in, monkeypatch):
        seen = []
        monkeypatch.setattr(appmod, 'process_image', lambda path: seen.append(path) or [])

        resp = logged_in.post('/upload', data={'image_data': png_data_url()})

        assert resp.status_code == 200
        assert len(seen) == 1
        assert seen[0].endswith('.png')
        assert os.path.dirname(seen[0]) == appmod.app.config['UPLOAD_FOLDER']
        # Deleted once processed; nothing displays it afterwards.
        assert not os.path.exists(seen[0])

    def test_uploaded_file_must_be_an_image(self, appmod, logged_in, monkeypatch):
        upload_dir = appmod.app.config['UPLOAD_FOLDER']
        before = set(os.listdir(upload_dir))
        monkeypatch.setattr(appmod, 'process_image', lambda path: pytest.fail('pipeline reached'))

        resp = logged_in.post('/upload', data={'file': (io.BytesIO(b'<script>x</script>'), 'shot.html')},
                              content_type='multipart/form-data')

        assert resp.status_code == 400
        assert b'not a screenshot we can read' in resp.data
        assert set(os.listdir(upload_dir)) == before

    def test_uploaded_file_name_and_extension_come_from_the_content(self, appmod, logged_in, monkeypatch):
        seen = []
        monkeypatch.setattr(appmod, 'process_image', lambda path: seen.append(path) or [])
        buf = io.BytesIO()
        Image.new('RGB', (8, 8)).save(buf, format='JPEG')
        buf.seek(0)

        resp = logged_in.post('/upload', data={'file': (buf, '../../evil.png.exe')},
                              content_type='multipart/form-data')

        assert resp.status_code == 200
        assert os.path.basename(seen[0]).endswith('.jpg')
        assert 'evil' not in seen[0]

    def test_gif_upload_is_converted_for_opencv(self, appmod, logged_in, monkeypatch):
        formats = []

        def fake_process(path):
            with Image.open(path) as img:
                formats.append((os.path.splitext(path)[1], img.format))
            return []

        monkeypatch.setattr(appmod, 'process_image', fake_process)
        buf = io.BytesIO()
        Image.new('P', (8, 8)).save(buf, format='GIF')
        buf.seek(0)

        logged_in.post('/upload', data={'file': (buf, 'shot.gif')}, content_type='multipart/form-data')

        assert formats == [('.png', 'PNG')]

    def test_missing_image_is_a_readable_page_not_json(self, logged_in):
        resp = logged_in.post('/upload', data={})

        assert resp.status_code == 400
        assert resp.mimetype == 'text/html'
        assert b'No file or pasted image was received' in resp.data


def eps_bytes(marker_path):
    """A minimal EPS file whose PostScript creates `marker_path` if run."""
    return (b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 8 8\n"
            b"(" + str(marker_path).encode() + b") (w) file closefile\nshowpage\n")


class TestImageFormatAllowlist:
    """Pillow used to probe every plugin it has. Loading an EPS runs
    Ghostscript on the uploaded PostScript, and the GIF->PNG conversion path
    did load it: a logged-in user could run PostScript on the server."""

    def test_eps_is_rejected_without_running_ghostscript(self, appmod, tmp_path):
        marker = tmp_path / 'ghostscript-ran'

        with pytest.raises(ValueError):
            appmod.image_format(eps_bytes(marker))
        assert not marker.exists()

    def test_eps_upload_is_refused(self, appmod, logged_in, monkeypatch, tmp_path):
        marker = tmp_path / 'ghostscript-ran'
        monkeypatch.setattr(appmod, 'process_image', lambda path: pytest.fail('pipeline reached'))

        resp = logged_in.post('/upload', data={'file': (io.BytesIO(eps_bytes(marker)), 'shot.eps')},
                              content_type='multipart/form-data')

        assert resp.status_code == 400
        assert not marker.exists()

    def test_eps_pasted_as_png_is_refused(self, appmod, tmp_path):
        marker = tmp_path / 'ghostscript-ran'
        url = 'data:image/png;base64,' + base64.b64encode(eps_bytes(marker)).decode()

        with pytest.raises(ValueError):
            appmod.decode_pasted_image(url)
        assert not marker.exists()

    def test_other_pillow_formats_are_refused(self, appmod):
        buf = io.BytesIO()
        Image.new('RGB', (8, 8)).save(buf, format='TIFF')

        with pytest.raises(ValueError):
            appmod.image_format(buf.getvalue())

    @pytest.mark.parametrize('fmt', ['PNG', 'JPEG', 'WEBP', 'BMP', 'GIF'])
    def test_screenshot_formats_are_accepted(self, appmod, fmt):
        buf = io.BytesIO()
        Image.new('RGB', (8, 8)).save(buf, format=fmt)

        assert appmod.image_format(buf.getvalue()) == fmt


class TestImageSizeLimit:
    def huge_png(self, appmod):
        # Solid colour compresses to a few hundred KB: well under the upload
        # limit, but ~45 MP once decoded.
        side = int(appmod.MAX_IMAGE_PIXELS ** 0.5) + 100
        buf = io.BytesIO()
        Image.new('L', (side, side)).save(buf, format='PNG')
        return buf.getvalue()

    def test_image_over_the_pixel_limit_is_refused(self, appmod):
        with pytest.raises(ValueError, match='megapixels'):
            appmod.image_format(self.huge_png(appmod))

    def test_huge_upload_never_reaches_the_pipeline(self, appmod, logged_in, monkeypatch):
        monkeypatch.setattr(appmod, 'process_image', lambda path: pytest.fail('pipeline reached'))

        resp = logged_in.post('/upload', data={'file': (io.BytesIO(self.huge_png(appmod)), 'shot.png')},
                              content_type='multipart/form-data')

        assert resp.status_code == 400
        assert b'megapixels' in resp.data

    def test_8k_screenshot_is_within_the_limit(self, appmod):
        assert 7680 * 4320 <= appmod.MAX_IMAGE_PIXELS


class TestLoginErrors:
    def test_unknown_user_and_wrong_password_look_the_same(self, client):
        name = f'user_{uuid.uuid4().hex[:8]}'
        client.post('/register', data={
            'username': name, 'email': f'{name}@example.com',
            'password': 'pw', 'confirm_password': 'pw',
        })

        wrong_pw = client.post('/login', data={'username': name, 'password': 'nope'})
        no_user = client.post('/login', data={'username': name + 'x', 'password': 'nope'})

        assert b'Invalid username or password.' in wrong_pw.data
        assert b'Invalid username or password.' in no_user.data


class TestUltralyticsSideEffects:
    """Importing ultralytics replaces PIL.Image.open with a wrapper that, on
    any image Pillow cannot open, calls check_requirements('pi-heif'). With
    ultralytics' defaults that runs `pip install pi-heif` (or `uv pip install`)
    inside the web process, i.e. every rejected upload on a fresh server
    installed a package from PyPI. It also sends usage analytics on every
    prediction. The detector module switches both off before importing it."""

    def test_detector_import_turns_off_autoinstall_and_analytics(self, repo_root):
        code = ('import Src.ImageDetector.modified_detect_text\n'
                'from ultralytics import utils\n'
                'print(utils.AUTOINSTALL, utils.ONLINE)\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith('YOLO_')}

        result = subprocess.run([sys.executable, '-c', code], cwd=repo_root, env=env,
                                capture_output=True, text=True, timeout=300)

        assert result.returncode == 0, result.stderr
        assert result.stdout.split()[-2:] == ['False', 'False']

    def test_rejected_image_never_starts_a_subprocess(self, appmod, monkeypatch, tmp_path):
        started = []

        def record(*args, **kwargs):
            # Raising (not pytest.fail) because ultralytics retries and
            # swallows errors from its install attempt.
            started.append(args)
            raise OSError('subprocess blocked by test')

        for name in ('check_output', 'check_call', 'run', 'Popen'):
            monkeypatch.setattr(subprocess, name, record)

        for junk in (b'not an image', eps_bytes(tmp_path / 'ghostscript-ran')):
            with pytest.raises(ValueError):
                appmod.image_format(junk)
        assert started == []
