"""kitty-cmd-k — one cmd+k picker for git worktrees and projects.

Install:
    git clone https://github.com/shaunchander/kitty-cmd-k ~/.config/kitty/kitty-cmd-k

kitty.conf:
    map cmd+k kitten kitty-cmd-k/cmd_k.py --projects ~/code

Flags:
    --projects <dir>   root of the Projects view (default: ~)

kitty runs main() in an overlay window; it returns a JSON description of the
tabs to open. handle_result() then runs inside kitty's own process and turns
that into launch / goto-layout calls. Only main() needs the sibling modules.
"""

import json
import os
import re
import shlex
from pathlib import Path

from cmdk_picker import run_picker
from cmdk_session import SessionError, build_tabs, tomllib
from cmdk_views import ProjectsView, WorktreeView


# ── Entry point (overlay window) ─────────────────────────────────────────


def parse_args(args):
    """args[0] is the kitten path (kitty convention); the rest are the flags from the map line."""
    options = {'projects': Path.home()}
    tokens = list(args[1:])
    while tokens:
        tok = tokens.pop(0)
        if tok == '--projects' and tokens:
            options['projects'] = Path(tokens.pop(0)).expanduser()
        elif tok.startswith('--projects='):
            options['projects'] = Path(tok.split('=', 1)[1]).expanduser()
    return options


def _fail(message):
    print(f'kitty-cmd-k: {message}')
    input('Press Enter to close...')
    return None


def main(args):
    if tomllib is None:
        return _fail('needs Python 3.11+ (tomllib); update kitty to 0.31 or newer.')

    options = parse_args(args)
    cwd = os.getcwd()
    views = [WorktreeView(cwd), ProjectsView(cwd, options['projects'])]

    # Start on the first view that applies here (Worktrees inside a repo, else Projects).
    start = next((i for i, v in enumerate(views) if v.available), 0)
    result = run_picker(views, start)
    if not result:
        return None

    try:
        tabs = build_tabs(result['path'], result.get('branch'), result.get('repo_root'))
    except SessionError as e:
        return _fail(str(e))
    return json.dumps({'tabs': tabs})


# ── Result handler (inside kitty's process) ──────────────────────────────


def has_cwd(launch_args):
    return any(a == '--cwd' or a.startswith('--cwd=') for a in launch_args)


def launch_cmd(launch_args, cwd, title=None):
    """Build a `launch` remote-control command; title != None creates the tab."""
    cmd = ('launch', '--type', 'tab', '--tab-title', title) if title is not None else ('launch',)
    if not has_cwd(launch_args):
        cmd += ('--cwd', cwd)
    return cmd + tuple(launch_args)


def report_error(boss, message):
    """kitty's process has no visible stdout; show_error opens an error window."""
    try:
        boss.show_error('kitty-cmd-k', message)
    except Exception:
        print(f'kitty-cmd-k: {message}')


def window_from_launch_response(boss, response):
    """`launch` answers with the new window's id as a string ('0' if none). Map it to the Window."""
    try:
        return boss.window_id_map.get(int(response))
    except (TypeError, ValueError):
        return None


def open_tab(boss, tab):
    # Splits and goto-layout are addressed to the tab's first window so they land in the
    # new tab even if focus moved (e.g. a launch line with --keep-focus).
    anchor = None
    for j, launch in enumerate(tab['launches']):
        args = shlex.split(launch['args'])
        cmd = launch_cmd(args, launch['cwd'], title=tab['title'] if j == 0 else None)
        window = window_from_launch_response(boss, boss.call_remote_control(anchor, cmd))
        if j == 0:
            anchor = window
            boss.call_remote_control(anchor, ('goto-layout', tab['layout']))


def handle_result(args, answer, target_window_id, boss):
    if not answer:
        return
    try:
        tabs = json.loads(answer).get('tabs') or []
    except (ValueError, AttributeError) as e:
        report_error(boss, f'could not read picker result: {e}')
        return

    try:
        open_titles = {
            tab.get('title')
            for os_win in json.loads(boss.call_remote_control(None, ('ls',)))
            for tab in os_win.get('tabs', [])
        }
    except Exception:
        open_titles = set()

    for tab in tabs:
        title = tab['title']
        if title in open_titles:
            boss.call_remote_control(None, ('focus-tab', '--match', f'title:^{re.escape(title)}$'))
            continue
        try:
            open_tab(boss, tab)
        except Exception as e:
            report_error(boss, f'could not open tab "{title}": {e}')
        open_titles.add(title)
