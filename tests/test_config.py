"""Configuration paths must not depend on the process working directory."""

import os


def test_relative_paths_resolve_against_repo_root(appmod, repo_root):
    assert appmod.repo_path('uploads') == os.path.join(repo_root, 'uploads')


def test_absolute_paths_are_kept(appmod, tmp_path):
    assert appmod.repo_path(str(tmp_path)) == str(tmp_path)


def test_configured_paths_are_absolute(appmod):
    for key in ('DATABASE', 'MODEL_PATH', 'UPLOAD_FOLDER'):
        assert os.path.isabs(appmod.app.config[key]), key


def test_default_model_path_points_at_the_committed_weights(appmod, repo_root):
    if 'MODEL_PATH' not in os.environ:
        assert appmod.app.config['MODEL_PATH'] == os.path.join(repo_root, 'Models', 'BOX_TRAINED.pt')
    assert os.path.exists(appmod.app.config['MODEL_PATH'])
