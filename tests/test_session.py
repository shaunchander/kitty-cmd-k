from pathlib import Path

import pytest

from cmdk_session import (
    SessionError, build_tabs, expand_vars, panes_to_tabs, parse_session, resolve_session_config,
    template_variables,
)


def test_expand_vars_leaves_unknown():
    assert expand_vars('{repo} ({branch}) {nope}', {'repo': 'r', 'branch': 'b'}) == 'r (b) {nope}'


def test_template_variables_aliases():
    v = template_variables('/x/proj-wt', 'feat', '/x/proj.git')
    assert v == {'branch': 'feat', 'repo': 'proj', 'path': '/x/proj-wt', 'basename': 'proj-wt',
                 'FOLDER_NAME': 'proj-wt', 'PROJECT_DIR': '/x/proj-wt'}


def test_parse_session_multi_tab_and_ignored_directives():
    text = '''
    # comment
    new_tab first
    layout tall
    cd /a
    launch --title editor nvim
    focus
    launch --location=hsplit
    new_os_window
    new_tab
    cd ~
    launch zsh
    focus_tab 1
    '''
    tabs = parse_session(text, 'fallback')
    assert [t['title'] for t in tabs] == ['first', 'fallback']
    assert tabs[0]['layout'] == 'tall'
    assert tabs[0]['launches'] == [{'args': '--title editor nvim', 'cwd': '/a'},
                                   {'args': '--location=hsplit', 'cwd': '/a'}]
    assert tabs[1]['layout'] == 'splits'
    assert tabs[1]['launches'][0]['cwd'] != '~'   # expanded


def test_parse_session_launch_before_new_tab_makes_implicit_tab():
    tabs = parse_session('launch htop', 'implicit')
    assert tabs == [{'title': 'implicit', 'layout': 'splits', 'launches': [{'args': 'htop', 'cwd': str(Path.home())}]}]


def test_panes_to_tabs_location_from_second_pane_and_layout_key():
    config = {'layout': 'tall', 'panes': [
        {'title': 'editor', 'command': '$EDITOR "{path}"'},
        {'title': 'shell', 'location': 'vsplit'},
        {'cwd': '~/{basename}'},
    ]}
    tabs = panes_to_tabs(config, {'path': '/p q', 'basename': 'b'}, '/p q', 'T')
    assert tabs[0]['title'] == 'T' and tabs[0]['layout'] == 'tall'
    args = [l['args'] for l in tabs[0]['launches']]
    assert args[0] == "--title editor '$EDITOR' '/p q'"
    assert args[1] == '--location=vsplit --title shell'
    assert args[2] == '--location=hsplit'
    assert tabs[0]['launches'][2]['cwd'].endswith('/b') and '~' not in tabs[0]['launches'][2]['cwd']


def test_panes_bad_quoting_is_reported():
    with pytest.raises(SessionError, match='No closing quotation'):
        panes_to_tabs({'panes': [{'command': 'echo "oops'}]}, {}, '/p', 'T')


def test_untitled_tabs_get_unique_titles(config_dir, tmp_path):
    (config_dir / 'cmd-k.toml').write_text('[default]\nsession_file = "two.conf"\n')
    (config_dir / 'two.conf').write_text('new_tab\nlaunch\nnew_tab\nlaunch\nnew_tab named\nlaunch\n')
    target = tmp_path / 'proj'
    target.mkdir()
    assert [t['title'] for t in build_tabs(str(target), None, None)] == ['proj (proj)', 'proj (proj) (2)', 'named']


def test_build_tabs_without_any_config_is_one_shell(config_dir, tmp_path):
    target = tmp_path / 'proj'
    target.mkdir()
    tabs = build_tabs(str(target), 'main', str(target))
    assert tabs == [{'title': 'proj (proj)', 'layout': 'splits', 'launches': [{'args': '', 'cwd': str(target)}]}]


def test_per_repo_config_with_relative_session_file(config_dir, tmp_path):
    target = tmp_path / 'proj'
    target.mkdir()
    (target / '.kitty-cmd-k.toml').write_text('session_file = "layouts/ide.conf"\ntab_title = "ignored"\n')
    (target / 'layouts').mkdir()
    (target / 'layouts' / 'ide.conf').write_text('new_tab {repo} [{branch}]\ncd {PROJECT_DIR}\nlaunch nvim\nlaunch --location=vsplit\n')
    tabs = build_tabs(str(target), 'dev', str(target))
    assert tabs[0]['title'] == 'proj [dev]'
    assert tabs[0]['launches'][0] == {'args': 'nvim', 'cwd': str(target)}


def test_repo_root_config_applies_to_linked_worktree(config_dir, tmp_path):
    root, wt = tmp_path / 'root', tmp_path / 'root-feat'
    root.mkdir(); wt.mkdir()
    (root / '.kitty-cmd-k.toml').write_text('tab_title = "R {basename}"\n[[panes]]\ncommand = "top"\n')
    tabs = build_tabs(str(wt), 'feat', str(root))
    assert tabs[0]['title'] == 'R root-feat'
    assert tabs[0]['launches'] == [{'args': 'top', 'cwd': str(wt)}]


def test_central_config_match_then_default(config_dir, tmp_path):
    (config_dir / 'cmd-k.toml').write_text('''
[[sessions]]
match = "api$"
tab_title = "API {basename}"
[[sessions.panes]]
command = "make dev"

[default]
session_file = "sessions/default.conf"
''')
    (config_dir / 'sessions').mkdir()
    (config_dir / 'sessions' / 'default.conf').write_text('new_tab {FOLDER_NAME}\nlaunch\n')

    api, other = tmp_path / 'my-api', tmp_path / 'other'
    api.mkdir(); other.mkdir()
    assert build_tabs(str(api), None, str(api))[0]['title'] == 'API my-api'
    assert build_tabs(str(other), None, None)[0]['title'] == 'other'
    assert resolve_session_config(str(other), None)[1] == config_dir


def test_missing_session_file_raises(config_dir, tmp_path):
    (config_dir / 'cmd-k.toml').write_text('[default]\nsession_file = "~/nope/none.conf"\n')
    with pytest.raises(SessionError, match='session_file not found'):
        build_tabs(str(tmp_path), None, None)


def test_bad_toml_is_reported(config_dir, tmp_path):
    (config_dir / 'cmd-k.toml').write_text('this is = not [toml')
    with pytest.raises(SessionError, match='cmd-k.toml'):
        resolve_session_config(str(tmp_path), None)


def test_bad_match_regex_is_reported(config_dir, tmp_path):
    (config_dir / 'cmd-k.toml').write_text('[[sessions]]\nmatch = "-(ui|web"\n')
    with pytest.raises(SessionError, match='bad match regex'):
        build_tabs(str(tmp_path), None, None)


def test_empty_config_files_fall_through(config_dir, tmp_path):
    (config_dir / 'cmd-k.toml').write_text('# nothing here\n')
    (tmp_path / '.kitty-cmd-k.toml').write_text('')
    assert resolve_session_config(str(tmp_path), None) == ({}, None)
