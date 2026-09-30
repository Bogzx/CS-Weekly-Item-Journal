"""Tests for request-handling hardening in app.py."""

import base64
import io
import os
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


@pytest.fixture
def client(appmod):
    appmod.app.config['TESTING'] = True
    with appmod.app.test_client() as client:
        yield client


@pytest.fixture
def logged_in(client):
    name = f'user_{uuid.uuid4().hex[:8]}'
    client.post('/register', data={
        'username': name, 'email': f'{name}@example.com',
        'password': 'pw-123456', 'confirm_password': 'pw-123456',
    })
    client.post('/login', data={'username': name, 'password': 'pw-123456'})
    return client


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
        os.remove(seen[0])


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
