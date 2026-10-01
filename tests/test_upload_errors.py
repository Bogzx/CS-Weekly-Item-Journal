"""What an upload that fails returns: the right status, and no internals."""

import io

from PIL import Image

from Src.ImageDetector.modified_detect_text import DetectionError


def upload(client):
    buf = io.BytesIO()
    Image.new('RGB', (4, 4)).save(buf, format='PNG')
    buf.seek(0)
    return client.post('/upload', data={'file': (buf, 'shot.png')}, content_type='multipart/form-data')


def test_no_drop_panel_is_a_422_with_the_reason(appmod, logged_in, monkeypatch):
    def no_panel(path):
        raise DetectionError('No weekly-drop panel found in shot.png at confidence >= 0.4.')

    monkeypatch.setattr(appmod, 'process_image', no_panel)

    resp = upload(logged_in)

    assert resp.status_code == 422
    assert b'No weekly-drop panel found' in resp.data


def test_unreadable_image_is_a_400(appmod, logged_in, monkeypatch):
    def unreadable(path):
        raise ValueError(f'Could not read image at {path}')

    monkeypatch.setattr(appmod, 'process_image', unreadable)

    resp = upload(logged_in)

    assert resp.status_code == 400
    assert b'not a screenshot we can read' in resp.data
    assert b'Could not read image at' not in resp.data  # the server path stays private


def test_unexpected_error_is_a_500_without_details(appmod, logged_in, monkeypatch, caplog):
    def broken(names):
        raise RuntimeError('database is locked at /srv/secret/path/items.db')

    monkeypatch.setattr(appmod, 'process_image', lambda path: ['a', 'b', 'c', 'd'])
    monkeypatch.setattr(appmod, 'match_items_in_database', broken)

    resp = upload(logged_in)

    assert resp.status_code == 500
    assert b'Something went wrong while processing the screenshot' in resp.data
    assert b'/srv/secret/path' not in resp.data
    assert 'database is locked' in caplog.text  # ...but the log has it


def test_upload_file_is_deleted_even_when_processing_fails(appmod, logged_in, monkeypatch):
    import os

    seen = []

    def no_panel(path):
        seen.append(path)
        raise DetectionError('No weekly-drop panel found')

    monkeypatch.setattr(appmod, 'process_image', no_panel)

    upload(logged_in)

    assert seen and not os.path.exists(seen[0])
