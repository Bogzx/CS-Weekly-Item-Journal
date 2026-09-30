"""Shared pytest fixtures.

Importing app.py has side effects (it creates the upload folder and runs
initialize_database against app.config['DATABASE']), so every test run is
pointed at a throwaway SQLite file via the DATABASE_PATH environment variable
before the import happens. The detection model is NOT loaded on import -- see
get_processor() in app.py -- so this stays fast.
"""

import os
import sys
import tempfile
import uuid

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import app.py as a top-level module, and make sure it talks to a scratch DB.
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault(
    'DATABASE_PATH', os.path.join(tempfile.gettempdir(), 'cswij_test_items.db')
)
os.environ.setdefault('SECRET_KEY', 'test-secret-not-a-real-key')


@pytest.fixture(scope='session')
def repo_root():
    return REPO_ROOT


@pytest.fixture(scope='session')
def appmod():
    """The imported app module."""
    import app
    return app


@pytest.fixture
def client(appmod):
    appmod.app.config['TESTING'] = True
    with appmod.app.test_client() as client:
        yield client


def register(client, name, password='pw-123456'):
    return client.post('/register', data={
        'username': name, 'email': f'{name}@example.com',
        'password': password, 'confirm_password': password,
    })


@pytest.fixture
def logged_in(client):
    name = f'user_{uuid.uuid4().hex[:8]}'
    register(client, name)
    client.post('/login', data={'username': name, 'password': 'pw-123456'})
    return client
