"""End-to-end against a throwaway kitty instance: runs the real kitten via
remote control and checks the tab it creates. Opens a kitty window briefly.

Opt in with:  CMDK_E2E=1 python3 -m pytest tests/test_kitty_e2e.py
"""

import glob
import json
import os
import shutil
import signal
import subprocess
import time

import pytest

from conftest import REPO, git

pytestmark = pytest.mark.skipif(
    os.environ.get('CMDK_E2E') != '1' or not shutil.which('kitty'),
    reason='set CMDK_E2E=1 (and have kitty on PATH) to run the live kitty test',
)


@pytest.fixture
def kitty_instance(tmp_path, repo):
    sock = str(tmp_path / 'kitty.sock')
    proc = subprocess.Popen(
        ['kitty', '--listen-on', 'unix:' + sock, '-o', 'allow_remote_control=yes',
         '-o', 'startup_session=none', '--directory', str(repo), 'sh'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(80):
        if glob.glob(sock + '*'):
            break
        time.sleep(0.25)
    else:
        os.killpg(proc.pid, signal.SIGTERM)
        pytest.fail('kitty did not start')
    time.sleep(1.0)

    def rc(*args):
        r = subprocess.run(['kitty', '@', '--to', 'unix:' + glob.glob(sock + '*')[0], *args],
                           capture_output=True, text=True, timeout=20)
        return r.stdout

    yield rc
    os.killpg(proc.pid, signal.SIGTERM)


def tabs(rc):
    return [{'title': t['title'], 'active': t['is_active'], 'layout': t['layout'],
             'windows': [(w['title'], os.path.basename(w['cwd'])) for w in t['windows']]}
            for osw in json.loads(rc('ls')) for t in osw['tabs']]


def test_open_worktree_then_focus_existing(kitty_instance, repo, tmp_path):
    rc = kitty_instance
    git('worktree', 'add', '-q', str(repo.parent / 'wt'), '-b', 'wt', cwd=repo)
    (repo / '.kitty-cmd-k.toml').write_text(f'session_file = "{tmp_path}/layout.conf"\n')
    (tmp_path / 'layout.conf').write_text(
        'new_tab e2e {basename} [{branch}]\nlayout splits\ncd {path}\n'
        'launch --title editor sh\nlaunch --location=vsplit --title side sh\nlaunch --location=hsplit --cwd=current --title shell sh\n')

    rc('kitten', str(REPO / 'cmd_k.py'), '--projects', str(tmp_path))
    time.sleep(1.5)
    rc('send-text', 'j'); time.sleep(0.3)
    rc('send-text', '\r'); time.sleep(2.5)

    ts = tabs(rc)
    new = [t for t in ts if t['title'] == 'e2e wt [wt]']
    assert len(new) == 1, ts
    assert new[0]['layout'] == 'splits'
    assert new[0]['windows'] == [('editor', 'wt'), ('side', 'wt'), ('shell', 'wt')]

    # again from inside the new tab: focuses, does not duplicate
    rc('kitten', str(REPO / 'cmd_k.py')); time.sleep(1.5)
    rc('send-text', 'j'); time.sleep(0.3)
    rc('send-text', '\r'); time.sleep(1.5)
    ts2 = tabs(rc)
    assert len(ts2) == len(ts)
    assert [t for t in ts2 if t['title'] == 'e2e wt [wt]'][0]['active']

    # q cancels without side effects
    rc('kitten', str(REPO / 'cmd_k.py')); time.sleep(1.0)
    rc('send-text', 'q'); time.sleep(1.0)
    assert len(tabs(rc)) == len(ts)
