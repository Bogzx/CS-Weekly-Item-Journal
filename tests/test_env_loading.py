"""Settings in .env reach every module, however early it reads them.

Src/Web/auth.py, Src/Web/history.py and the detector read their settings
from the environment when they are imported. app.py used to call
load_dotenv() after importing them, so SESSION_LIFETIME_DAYS,
CS2_RESET_HOUR_UTC and YOLO_* in .env were silently ignored.

Each check runs in a fresh interpreter: the modules are already imported in
this one.
"""

import os
import subprocess
import sys

PROBE = '''
import logging, os
import app
from Src.Web import auth, history
print(auth.REMEMBERED_SESSION_LIFETIME.days)
print(history.CS2_RESET_HOUR_UTC)
print(os.environ["YOLO_OFFLINE"])
print(logging.getLogger().getEffectiveLevel())
print(bool(logging.getLogger().handlers))
'''

# Anything that could leak in from the environment running the tests.
SETTINGS = ('SESSION_LIFETIME_DAYS', 'CS2_RESET_HOUR_UTC', 'YOLO_OFFLINE', 'YOLO_AUTOINSTALL',
            'LOG_LEVEL', 'DOTENV_PATH')


def probe(repo_root, tmp_path, dotenv_text=None):
    env = {k: v for k, v in os.environ.items() if k not in SETTINGS}
    env['DATABASE_PATH'] = str(tmp_path / 'items.db')
    env['SECRET_KEY'] = 'env-loading-test-not-a-real-key'
    if dotenv_text is not None:
        (tmp_path / 'test.env').write_text(dotenv_text)
        env['DOTENV_PATH'] = str(tmp_path / 'test.env')
    else:
        env['DOTENV_PATH'] = str(tmp_path / 'missing.env')
    result = subprocess.run([sys.executable, '-c', PROBE], cwd=repo_root, env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    return result.stdout.split()[-5:]


def test_dotenv_values_reach_modules_that_read_them_at_import(repo_root, tmp_path):
    days, reset_hour, yolo_offline, level, _ = probe(repo_root, tmp_path, (
        'SESSION_LIFETIME_DAYS=7\n'
        'CS2_RESET_HOUR_UTC=2\n'
        'YOLO_OFFLINE=false\n'
        'LOG_LEVEL=warning\n'
    ))

    assert days == '7'
    assert reset_hour == '2'
    assert yolo_offline == 'false'   # the detector's default must not override .env
    assert level == '30'             # WARNING


def test_defaults_without_a_dotenv_file(repo_root, tmp_path):
    days, reset_hour, yolo_offline, level, has_handler = probe(repo_root, tmp_path)

    assert days == '120'
    assert reset_hour == '1'
    assert yolo_offline == 'true'
    assert level == '20'             # INFO, under any server, not only `python app.py`
    assert has_handler == 'True'
