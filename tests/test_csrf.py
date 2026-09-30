"""CSRF tokens on every state-changing POST (L5)."""

import re
import uuid

import pytest

from conftest import register

POST_ROUTES = ['/login', '/register', '/upload', '/add_to_journal',
               '/remove_from_journal', '/clear_journal']


@pytest.mark.parametrize('path', POST_ROUTES)
def test_post_without_token_is_rejected(logged_in, path):
    resp = logged_in.post(path, data={'x': '1'}, csrf=False)

    assert resp.status_code == 400
    assert b'security token' in resp.data


def test_wrong_token_is_rejected(appmod, logged_in):
    # Login clears the session, so render a page first: without a token in
    # the session this was rejected before the comparison ever ran, and the
    # test passed even with a check that accepted any token.
    logged_in.get('/')
    with logged_in.session_transaction() as sess:
        real = sess[appmod.CSRF_SESSION_KEY]

    forged = logged_in.post('/clear_journal', data={'csrf_token': 'x' * len(real)}, csrf=False)
    genuine = logged_in.post('/clear_journal', data={'csrf_token': real}, csrf=False)

    assert forged.status_code == 400
    assert genuine.status_code == 302


@pytest.mark.parametrize('token', ['é', '\u2603' * 43])
def test_non_ascii_token_is_a_400_not_a_500(logged_in, token):
    logged_in.get('/')  # renders a form, so the session holds a real token
    resp = logged_in.post('/clear_journal', data={'csrf_token': token}, csrf=False)

    assert resp.status_code == 400


def test_token_changes_at_login(appmod, client):
    """session.clear() at login drops the anonymous token, so one planted
    before login (session fixation of the token) is not valid afterwards."""
    name = f'user_{uuid.uuid4().hex[:8]}'
    register(client, name)
    with client.session_transaction() as sess:
        before = sess[appmod.CSRF_SESSION_KEY]

    client.post('/login', data={'username': name, 'password': 'pw-123456'})
    client.get('/')
    with client.session_transaction() as sess:
        after = sess[appmod.CSRF_SESSION_KEY]

    assert after != before
    assert client.post('/clear_journal', data={'csrf_token': before}, csrf=False).status_code == 400


def test_token_from_the_rendered_form_is_accepted(appmod, client):
    """End to end, the way a browser does it: GET the form, post it back."""
    name = f'user_{uuid.uuid4().hex[:8]}'
    register(client, name)

    page = client.get('/login').get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    resp = client.post('/login', data={'username': name, 'password': 'pw-123456',
                                       'csrf_token': token}, csrf=False)

    assert resp.status_code == 302


def test_every_post_form_in_the_templates_carries_the_token(repo_root):
    import glob
    import os

    missing = []
    for path in glob.glob(os.path.join(repo_root, 'templates', '*.html')):
        html = open(path, encoding='utf-8').read()
        for form in re.findall(r'<form\b[^>]*method="post"[^>]*>(.*?)</form>', html, re.S | re.I):
            if 'csrf_field()' not in form:
                missing.append(os.path.basename(path))
    assert not missing


def test_get_requests_are_unaffected(client):
    assert client.get('/login').status_code == 200


def test_can_be_disabled(appmod, logged_in):
    appmod.app.config['CSRF_ENABLED'] = False
    try:
        resp = logged_in.post('/clear_journal', data={}, csrf=False)
    finally:
        appmod.app.config['CSRF_ENABLED'] = True

    assert resp.status_code == 302


class TestUploadLimit:
    def test_limit_is_a_screenshot_not_a_quarter_gigabyte(self, appmod):
        assert appmod.app.config['MAX_CONTENT_LENGTH'] == 20 * 1024 * 1024
        assert appmod.app.config['MAX_FORM_MEMORY_SIZE'] == appmod.app.config['MAX_CONTENT_LENGTH']

    def test_oversized_upload_is_refused_with_a_message(self, appmod, logged_in):
        body = b'x' * (appmod.app.config['MAX_CONTENT_LENGTH'] + 1)

        resp = logged_in.post('/upload', data={'image_data': body.decode()})

        assert resp.status_code == 302
        with logged_in.session_transaction() as sess:
            messages = [m for _, m in sess.get('_flashes', [])]
        assert any('too large (limit 20 MB)' in m for m in messages)
