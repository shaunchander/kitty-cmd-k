import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def git(*args, cwd):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A git repo with one commit at <tmp>/main-repo, so worktrees land as siblings."""
    path = tmp_path / 'main-repo'
    path.mkdir()
    git('init', '-q', '-b', 'main', cwd=path)
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init', cwd=path)
    return path


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """An isolated kitty config dir; cmdk_session reads cmd-k.toml from here."""
    d = tmp_path / 'kitty-config'
    d.mkdir()
    monkeypatch.setenv('KITTY_CONFIG_DIRECTORY', str(d))
    return d
