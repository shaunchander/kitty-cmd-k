"""Drives run_picker through a pseudo-terminal with real keystrokes.

Needs a POSIX pty (skipped on Windows); does not need kitty.
"""

import json
import os
import re
import select
import sys
import time

import pytest

from conftest import REPO

pty = pytest.importorskip('pty')
fcntl = pytest.importorskip('fcntl')
termios = pytest.importorskip('termios')
import struct  # noqa: E402

CHILD = f'''
import json, sys
sys.path.insert(0, {str(REPO)!r})
from cmdk_picker import View, CreateError, filter_rows, run_picker

class Static(View):
    can_create = True
    create_prompt = 'Name: '
    def __init__(self, name, items):
        self.name = name
        self.items = [{{'label': i, 'key': i}} for i in items]
    def rows(self, q): return filter_rows(self.items, q, lambda r: r['label'])
    def render(self, row, width): return row['label']
    def help(self): return 'HELP-' + self.name
    def activate(self, row): return {{'view': self.name, 'label': row['label']}}
    def create(self, name):
        if name == 'bad':
            raise CreateError('bad name')
        return {{'view': self.name, 'created': name}}

r = run_picker([Static('A', ['alpha', 'beta', 'gamma', 'delta']), Static('B', ['one', 'two'])], 0)
print('\\nRESULT:' + json.dumps(r))
'''


def drive(keys, rows=12, cols=60):
    """Spawn the child picker in a pty, send keys, return (result, screen_text)."""
    pid, fd = pty.fork()
    if pid == 0:
        # fd 1 is the pty slave here; sys.stdout may be pytest's capture object
        fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        os.execv(sys.executable, [sys.executable, '-c', CHILD])
    out = b''

    def drain(seconds):
        nonlocal out
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    return False
                if not chunk:
                    return False
                out += chunk
        return True

    drain(1.0)
    for k in keys:
        os.write(fd, k.encode())
        drain(0.25)
    deadline = time.time() + 10
    while drain(0.2) and time.time() < deadline:
        pass
    if time.time() >= deadline:
        os.kill(pid, 9)
    os.waitpid(pid, 0)
    text = out.decode('utf-8', 'replace')
    m = re.search(r'RESULT:(.*)', text)
    result = json.loads(m.group(1).strip()) if m else 'NO-RESULT'
    plain = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', text)
    return result, plain


def test_enter_selects_after_j():
    result, _ = drive(['j', 'j', '\r'])
    assert result == {'view': 'A', 'label': 'gamma'}


def test_bracket_switches_view_and_G_gg():
    result, screen = drive([']', 'G', '\r'])
    assert result == {'view': 'B', 'label': 'two'}
    assert 'HELP-B' in screen
    result, _ = drive(['G', 'g', 'g', '\r'])
    assert result == {'view': 'A', 'label': 'alpha'}


def test_filter_then_esc_keeps_filter_then_enter():
    result, screen = drive(['/', 'ta', '\x1b', 'j', '\r'])
    assert result == {'view': 'A', 'label': 'delta'}     # beta, delta match; j moves to delta
    assert '/ ta' in screen


def test_q_closes_and_esc_clears_filter_first():
    assert drive(['q'])[0] is None
    result, _ = drive(['/', 'zzz', '\x1b', '\x1b', '\r'])   # esc leaves search, esc clears, enter opens alpha
    assert result == {'view': 'A', 'label': 'alpha'}


def test_n_prompt_error_then_success():
    result, screen = drive(['n', 'bad', '\r', '\x7f' * 3, 'good', '\r'])
    assert result == {'view': 'A', 'created': 'good'}
    assert 'bad name' in screen and 'Name: ' in screen


def test_n_prompt_escape_returns_to_list():
    result, _ = drive(['n', 'x', '\x1b', 'j', '\r'])
    assert result == {'view': 'A', 'label': 'beta'}


def test_arrow_keys_home_end_and_unknown_sequences_are_harmless():
    # down, down, up -> beta; Delete (ESC[3~) and F5 (ESC[15~) must not leak bytes into the filter
    result, _ = drive(['\x1b[B', '\x1b[B', '\x1b[A', '\x1b[3~', '\x1b[15~', '\r'])
    assert result == {'view': 'A', 'label': 'beta'}
    result, _ = drive(['\x1b[F', '\r'])           # End
    assert result == {'view': 'A', 'label': 'delta'}
    result, _ = drive(['G', '\x1b[H', '\r'])      # Home
    assert result == {'view': 'A', 'label': 'alpha'}


def test_alt_key_in_prompt_does_not_cancel_it():
    # alt+backspace (ESC DEL) and alt+b (ESC b) are common editing chords; a lone ESC still cancels
    result, screen = drive(['n', 'abc', '\x1b\x7f', '\x1bb', '\r'])
    assert result == {'view': 'A', 'created': 'abc'}
    result, _ = drive(['n', 'abc', '\x1b', '\r'])
    assert result == {'view': 'A', 'label': 'alpha'}


def test_ctrl_d_half_page():
    result, _ = drive(['\x04', '\r'], rows=12)         # body height 6 -> half page 3 -> delta
    assert result == {'view': 'A', 'label': 'delta'}
