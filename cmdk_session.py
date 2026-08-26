"""Session-layout resolution: which tab layout to open for a directory.

Resolution order, first hit wins:

  1. <target>/.kitty-cmd-k.toml
  2. <repo root>/.kitty-cmd-k.toml
  3. ~/.config/kitty/cmd-k.toml  -> first [[sessions]] whose `match` regex hits the path
  4. ~/.config/kitty/cmd-k.toml  -> [default]
  5. built in: one window running your shell in the target directory

A matched config describes the tab either with `session_file = "..."` (a file in
kitty's own session syntax; new_tab / layout / cd / launch are honoured, other
directives are ignored) or with inline `tab_title`, `layout` and [[panes]].

The output is a list of tab dicts, the JSON contract handed to handle_result():

    {'title': str, 'layout': str, 'launches': [{'args': str, 'cwd': str}, ...]}
"""

import os
import re
import shlex
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11; main() reports this before anything is resolved
    tomllib = None


PER_REPO_CONFIG = '.kitty-cmd-k.toml'
CENTRAL_CONFIG_NAME = 'cmd-k.toml'
DEFAULT_LAYOUT = 'splits'


class SessionError(Exception):
    """Config is broken or a configured session cannot be materialised. Shown to the user."""


def central_config_path():
    """~/.config/kitty/cmd-k.toml, honouring KITTY_CONFIG_DIRECTORY (kitty sets it for kittens)."""
    config_dir = os.environ.get('KITTY_CONFIG_DIRECTORY') or '~/.config/kitty'
    return Path(config_dir).expanduser() / CENTRAL_CONFIG_NAME


def load_toml(path):
    """Parsed TOML, or None if the file is unreadable. A syntax error is a SessionError."""
    if tomllib is None:
        return None
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f)
    except OSError:
        return None
    except tomllib.TOMLDecodeError as e:
        raise SessionError(f'{path}: {e}') from e


def _matches(session, target_path, config_path):
    pattern = str(session.get('match', ''))
    try:
        return re.search(pattern, target_path) is not None
    except re.error as e:
        raise SessionError(f'{config_path}: bad match regex {pattern!r}: {e}') from e


def resolve_session_config(target_path, repo_root):
    """Return (config_dict, base_dir). base_dir resolves relative session_file paths.

    An empty dict means nothing matched and the built-in default applies.
    """
    for base in (target_path, repo_root):
        if not base:
            continue
        candidate = Path(base) / PER_REPO_CONFIG
        if candidate.is_file():
            data = load_toml(candidate)
            if data:
                return data, candidate.parent

    central = central_config_path()
    config = load_toml(central) if central.is_file() else None
    if config:
        for session in config.get('sessions', []):
            if _matches(session, target_path, central):
                return session, central.parent
        if 'default' in config:
            return config['default'], central.parent
    return {}, None


def expand_vars(text, variables):
    """Replace {name} placeholders; unknown names are left untouched."""
    return re.sub(r'\{(\w+)\}', lambda m: variables.get(m.group(1), m.group(0)), text)


def template_variables(target_path, branch, repo_root):
    repo_name = Path(repo_root).name.removesuffix('.git') if repo_root else Path(target_path).name
    basename = Path(target_path).name
    return {
        'branch': branch or '',
        'repo': repo_name,
        'path': target_path,
        'basename': basename,
        # aliases kept for kitty session files written for other tools
        'FOLDER_NAME': basename,
        'PROJECT_DIR': target_path,
    }


def parse_session(text, default_title):
    """Parse kitty session syntax into tab dicts.

    Honoured: new_tab [title], layout <name>, cd <dir>, launch <args...>.
    Everything else (focus, new_os_window, os_window_*, ...) is ignored.
    """
    tabs, current_tab = [], None
    current_cwd = str(Path.home())
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('new_tab'):
            if current_tab is not None:
                tabs.append(current_tab)
            current_tab = {'title': line[7:].strip() or default_title, 'layout': DEFAULT_LAYOUT, 'launches': []}
        elif line.startswith('layout ') and current_tab is not None:
            current_tab['layout'] = line[7:].strip()
        elif line.startswith('cd '):
            current_cwd = os.path.expanduser(line[3:].strip())
        elif line.startswith('launch'):
            if current_tab is None:
                current_tab = {'title': default_title, 'layout': DEFAULT_LAYOUT, 'launches': []}
            current_tab['launches'].append({'args': line[6:].strip(), 'cwd': current_cwd})
    if current_tab is not None:
        tabs.append(current_tab)
    return tabs


def uniquify_titles(tabs):
    """Tabs are matched by title, so two untitled `new_tab` lines must not collide: 'x', 'x (2)', ..."""
    seen = {}
    for tab in tabs:
        base = tab['title']
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            tab['title'] = f'{base} ({seen[base]})'
    return tabs


def panes_to_tabs(config, variables, target_path, title):
    """Convert inline [[panes]] (title / command / location / cwd) into one tab dict."""
    launches = []
    for i, pane in enumerate(config.get('panes', [])):
        args = []
        if i > 0:
            args.append(f"--location={pane.get('location', 'hsplit')}")
        if pane.get('title'):
            args += ['--title', expand_vars(str(pane['title']), variables)]
        if pane.get('command'):
            command = expand_vars(str(pane['command']), variables)
            try:
                args += shlex.split(command)
            except ValueError as e:
                raise SessionError(f'pane command {command!r}: {e}') from e
        cwd = expand_vars(str(pane.get('cwd', target_path)), variables)
        launches.append({'args': shlex.join(args), 'cwd': os.path.expanduser(cwd)})
    return [{'title': title, 'layout': str(config.get('layout', DEFAULT_LAYOUT)), 'launches': launches}]


def build_tabs(target_path, branch, repo_root):
    """Resolve the session for target_path and return its tab dicts. Raises SessionError."""
    variables = template_variables(target_path, branch, repo_root)
    config, base_dir = resolve_session_config(target_path, repo_root)
    title = expand_vars(str(config.get('tab_title', '{repo} ({basename})')), variables)

    session_file = config.get('session_file')
    if session_file:
        template = Path(os.path.expanduser(str(session_file)))
        if not template.is_absolute() and base_dir is not None:
            template = base_dir / template
        if not template.is_file():
            raise SessionError(f'session_file not found: {template}')
        tabs = parse_session(expand_vars(template.read_text(), variables), title)
        if not tabs:
            raise SessionError(f'session_file has no new_tab or launch lines: {template}')
        return uniquify_titles(tabs)

    if config.get('panes'):
        return panes_to_tabs(config, variables, target_path, title)

    # Nothing configured: an empty launch makes kitty start its default shell.
    return [{'title': title, 'layout': str(config.get('layout', DEFAULT_LAYOUT)),
             'launches': [{'args': '', 'cwd': target_path}]}]
