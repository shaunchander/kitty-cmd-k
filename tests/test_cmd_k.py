import json
import re
from pathlib import Path

import cmd_k


def test_parse_args_projects_flag():
    assert cmd_k.parse_args(['cmd_k.py'])['projects'] == Path.home()
    assert cmd_k.parse_args(['cmd_k.py', '--projects', '~/code'])['projects'] == Path.home() / 'code'
    assert cmd_k.parse_args(['cmd_k.py', '--projects=/srv'])['projects'] == Path('/srv')
    assert cmd_k.parse_args(['cmd_k.py', '--projects'])['projects'] == Path.home()   # dangling flag


def test_launch_cmd_injects_cwd_only_when_absent():
    assert cmd_k.launch_cmd(['nvim'], '/p', title='T') == ('launch', '--type', 'tab', '--tab-title', 'T', '--cwd', '/p', 'nvim')
    assert cmd_k.launch_cmd(['--cwd=current', 'zsh'], '/p') == ('launch', '--cwd=current', 'zsh')
    assert cmd_k.launch_cmd(['--cwd', '/x'], '/p') == ('launch', '--cwd', '/x')
    assert cmd_k.launch_cmd([], '/p') == ('launch', '--cwd', '/p')


class FakeBoss:
    """Records remote-control calls; mimics the three things handle_result touches."""

    def __init__(self, open_tabs=()):
        self.calls = []
        self.errors = []
        self.window_id_map = {}
        self._open_tabs = list(open_tabs)
        self._next_id = 100

    def call_remote_control(self, window, args):
        self.calls.append((window, args))
        if args[0] == 'ls':
            return json.dumps([{'tabs': [{'title': t} for t in self._open_tabs]}])
        if args[0] == 'launch':
            self._next_id += 1
            self.window_id_map[self._next_id] = f'win{self._next_id}'
            return str(self._next_id)      # real kitty answers with the id as a string
        return None

    def show_error(self, title, message):
        self.errors.append((title, message))


def answer(*tabs):
    return json.dumps({'tabs': list(tabs)})


def test_handle_result_opens_tab_with_layout_and_splits():
    boss = FakeBoss()
    cmd_k.handle_result([], answer({'title': 'T', 'layout': 'tall', 'launches': [
        {'args': 'nvim', 'cwd': '/p'}, {'args': '--location=vsplit', 'cwd': '/p'}]}), 1, boss)
    cmds = [c for _, c in boss.calls]
    assert cmds[0] == ('ls',)
    assert cmds[1] == ('launch', '--type', 'tab', '--tab-title', 'T', '--cwd', '/p', 'nvim')
    assert cmds[2] == ('goto-layout', 'tall')
    assert cmds[3] == ('launch', '--cwd', '/p', '--location=vsplit')
    # splits are anchored to the first window of the new tab, not the invoking window
    assert boss.calls[3][0] == 'win101' and boss.calls[2][0] == 'win101'
    assert boss.errors == []


def test_handle_result_focuses_existing_tab():
    boss = FakeBoss(open_tabs=['proj (main)'])
    cmd_k.handle_result([], answer({'title': 'proj (main)', 'layout': 'splits', 'launches': [{'args': '', 'cwd': '/p'}]}), 1, boss)
    cmds = [c for _, c in boss.calls]
    assert cmds == [('ls',), ('focus-tab', '--match', f'title:^{re.escape("proj (main)")}$')]


def test_handle_result_same_title_twice_in_one_answer_opens_once():
    boss = FakeBoss()
    tab = {'title': 'dup', 'layout': 'splits', 'launches': [{'args': '', 'cwd': '/p'}]}
    cmd_k.handle_result([], answer(tab, dict(tab)), 1, boss)
    launches = [c for _, c in boss.calls if c[0] == 'launch']
    assert len(launches) == 1
    assert ('focus-tab', '--match', f'title:^{re.escape("dup")}$') in [c for _, c in boss.calls]


def test_handle_result_bad_tab_is_reported_and_others_still_open():
    boss = FakeBoss()
    cmd_k.handle_result([], answer(
        {'title': 'broken', 'layout': 'splits', 'launches': [{'args': 'zsh -c "unterminated', 'cwd': '/p'}]},
        {'title': 'fine', 'layout': 'splits', 'launches': [{'args': '', 'cwd': '/q'}]},
    ), 1, boss)
    assert len(boss.errors) == 1 and 'broken' in boss.errors[0][1]
    assert ('launch', '--type', 'tab', '--tab-title', 'fine', '--cwd', '/q') in [c for _, c in boss.calls]


def test_handle_result_survives_unresolvable_window_id():
    class NoWindowBoss(FakeBoss):
        def call_remote_control(self, window, args):
            super().call_remote_control(window, args)
            return '0' if args[0] == 'launch' else None
    boss = NoWindowBoss()
    cmd_k.handle_result([], answer({'title': 'T', 'layout': 'splits', 'launches': [
        {'args': '', 'cwd': '/p'}, {'args': '--location=hsplit', 'cwd': '/p'}]}), 1, boss)
    assert [c[0] for _, c in boss.calls] == ['ls', 'launch', 'goto-layout', 'launch']
    assert all(w is None for w, _ in boss.calls) and boss.errors == []


def test_handle_result_ignores_empty_and_garbage():
    boss = FakeBoss()
    cmd_k.handle_result([], '', 1, boss)
    cmd_k.handle_result([], None, 1, boss)
    assert boss.calls == []
    cmd_k.handle_result([], 'not json', 1, boss)
    assert boss.calls == [] and len(boss.errors) == 1


def test_handle_result_ls_failure_degrades_to_opening():
    class NoLsBoss(FakeBoss):
        def call_remote_control(self, window, args):
            if args[0] == 'ls':
                raise RuntimeError('boom')
            return super().call_remote_control(window, args)
    boss = NoLsBoss()
    cmd_k.handle_result([], answer({'title': 'T', 'layout': 'splits', 'launches': [{'args': '', 'cwd': '/p'}]}), 1, boss)
    assert any(c[0] == 'launch' for _, c in boss.calls) and boss.errors == []
