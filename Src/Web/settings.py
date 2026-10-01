"""Paths and environment parsing shared by the app's modules."""

import logging
import os

logger = logging.getLogger(__name__)

# Absolute path to the repository root, so that subprocesses and file lookups
# do not depend on the process working directory.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def repo_path(path):
    """Resolve a relative path against the repository root, not the CWD.

    The defaults (and the relative paths in .env.EXAMPLE) used to be resolved
    against whatever directory `python app.py` was launched from, so starting
    the app from anywhere but the repo root created an empty database and
    failed to find the model.
    """
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def env_bool(name, default):
    """Read a boolean from the environment, accepting 1/true/yes/on."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


# The placeholder shipped in .env.EXAMPLE. Anyone who copies that file without
# editing it would otherwise sign sessions with a key published on GitHub,
# which lets a visitor forge a cookie for any user_id.
PLACEHOLDER_SECRET_PREFIX = 'CHANGE_ME'


def resolve_secret_key(raw):
    """Return a usable session signing key.

    Falls back to a random per-process key (sessions end on restart) when the
    configured one is missing or is still the .env.EXAMPLE placeholder.
    """
    if not raw or raw.startswith(PLACEHOLDER_SECRET_PREFIX):
        logger.warning(
            "SECRET_KEY is unset or still the .env.EXAMPLE placeholder; using a "
            "random key. Logins will not survive a restart. See README 'Configure'."
        )
        return os.urandom(24)
    return raw
