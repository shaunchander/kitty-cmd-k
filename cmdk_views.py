"""The two built-in views: git worktrees of the current repo, and a project tree.

Both hand back `open_result(...)` dicts, which cmd_k.main() feeds to
cmdk_session.build_tabs(). A new view should return the same shape.
"""

import os
from pathlib import Path

from cmdk_git import GitError, create_worktree, get_branch, get_repo_root, get_toplevel, get_worktrees
from cmdk_picker import CreateError, View, filter_rows

SEARCH_MAX_DEPTH = 4   # how deep the Projects filter looks for repos below the root

ICON_BRANCH = ''      # U+E0A0, a Powerline glyph kitty renders itself (no font requirement)
ICON_CLOSED = '▸'
ICON_OPEN = '▾'


def open_result(path, branch=None, repo_root=None):
    """What a view returns to open `path`: branch and repo_root feed the session template variables."""
    return {'path': str(path), 'branch': branch, 'repo_root': repo_root}


# ── Filesystem helpers ───────────────────────────────────────────────────


def fkey(path):
    """Identity of a directory that survives case/symlink spelling differences (e.g. ~/desktop vs ~/Desktop)."""
    try:
        st = os.stat(path)
        return (st.st_dev, st.st_ino)
    except OSError:
        return str(path)


def is_git_repo(path):
    git_path = Path(path) / '.git'
    return git_path.is_dir() or git_path.is_file()


def list_dirs(path):
    """Visible subdirectories, case-insensitively sorted."""
    try:
        return sorted(
            (p for p in Path(path).iterdir() if p.is_dir() and not p.name.startswith('.')),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []


def display_path(path):
    try:
        return '~/' + str(Path(path).relative_to(Path.home()))
    except ValueError:
        return str(path)


# ── Worktrees ────────────────────────────────────────────────────────────


class WorktreeView(View):
    name = 'Worktrees'
    create_prompt = 'New worktree: '

    def __init__(self, cwd):
        self.worktrees = get_worktrees(cwd)
        self.repo_root = get_repo_root(cwd) if self.worktrees else None
        toplevel = get_toplevel(cwd) if self.worktrees else None
        current_key = fkey(toplevel) if toplevel else None
        width = max((len(w.get('branch', '???')) for w in self.worktrees), default=0)
        for w in self.worktrees:
            w['key'] = fkey(w['path'])
            w['current'] = w['key'] == current_key
            w['label'] = f"{w.get('branch', '???').ljust(width)}  {display_path(w['path'])}"

    @property
    def available(self):
        return bool(self.worktrees)

    @property
    def can_create(self):
        return self.available

    def subheader(self):
        if not self.available:
            return ''
        return f"{ICON_BRANCH} {Path(self.repo_root).name}  {display_path(self.repo_root)}"

    def empty_message(self):
        return 'Not inside a git repository — press ] for Projects'

    def help(self):
        return '[ ] view   j/k move   gg/G ends   enter open   n new worktree   / filter   q close'

    def rows(self, query):
        return filter_rows(self.worktrees, query, lambda w: w['label'])

    def render(self, row, width):
        marker = '\033[32m*\033[0m' if row['current'] else ' '
        return f"{marker} {row['label'][:max(0, width - 2)]}"

    def activate(self, row):
        return open_result(row['path'], row.get('branch'), self.repo_root)

    def open_any(self, row):
        return self.activate(row)

    def create(self, name):
        try:
            path = create_worktree(self.repo_root, name)
        except GitError as e:
            raise CreateError(str(e)) from e
        return open_result(path, get_branch(path), self.repo_root)


# ── Projects ─────────────────────────────────────────────────────────────


class ProjectsView(View):
    name = 'Projects'

    def __init__(self, cwd, root):
        self.root = Path(root)
        self.expanded = set()
        self._repo_index = None
        self._expand_to(cwd)

    def _expand_to(self, cwd):
        """If cwd lives under root, unfold the tree down to it and select it on open."""
        root_key = fkey(self.root)
        chain = [Path(cwd), *Path(cwd).parents]
        for i, ancestor in enumerate(chain):
            if fkey(ancestor) != root_key:
                continue
            # Walk root -> cwd unfolding folders; stop at the first repo since repos are leaves.
            for d in reversed(chain[:i]):
                self.initial_key = fkey(d)
                if is_git_repo(d):
                    break
                self.expanded.add(fkey(d))
            return

    @property
    def available(self):
        return self.root.is_dir()

    def subheader(self):
        return display_path(self.root)

    def empty_message(self):
        return f'{display_path(self.root)} is not a directory — check the --projects flag'

    def help(self):
        return '[ ] view   j/k move   h/l fold   enter open   o open folder   / filter   q close'

    def _row(self, child, depth, label):
        kind = 'repo' if is_git_repo(child) else 'folder'
        key = fkey(child)
        return {'path': str(child), 'name': child.name, 'depth': depth, 'kind': kind,
                'key': key, 'label': label, 'open': kind == 'folder' and key in self.expanded}

    def _tree_rows(self):
        rows = []

        def walk(directory, depth):
            for child in list_dirs(directory):
                row = self._row(child, depth, child.name)
                rows.append(row)
                if row['open']:
                    walk(child, depth + 1)

        walk(self.root, 0)
        return rows

    def _search_rows(self):
        """Flat index of every repo under root (built once) for fuzzy filtering."""
        if self._repo_index is None:
            index = []

            def walk(directory, depth):
                for child in list_dirs(directory):
                    if is_git_repo(child):
                        index.append(self._row(child, 0, str(child.relative_to(self.root))))
                    elif depth < SEARCH_MAX_DEPTH:
                        walk(child, depth + 1)

            walk(self.root, 0)
            self._repo_index = index
        return self._repo_index

    def rows(self, query):
        if query:
            return filter_rows(self._search_rows(), query, lambda r: r['label'])
        return self._tree_rows()

    def render(self, row, width):
        indent = '  ' * row['depth']
        if row['kind'] == 'repo':
            icon = f'\033[32m{ICON_BRANCH}\033[0m'
        else:
            icon = ICON_OPEN if row['open'] else ICON_CLOSED
        label = row['label'][:max(0, width - len(indent) - 2)]
        return f'{indent}{icon} {label}'

    def activate(self, row):
        """Enter opens a repo and toggles a folder."""
        if row['kind'] == 'repo':
            return self.open_any(row)
        self.toggle(row, 'left' if row['open'] else 'right')
        return None

    def toggle(self, row, direction):
        """right expands; left collapses, or moves to the parent when already collapsed."""
        if direction == 'right':
            if row['kind'] == 'folder':
                self.expanded.add(row['key'])
            return None
        if row['open']:
            self.expanded.discard(row['key'])
            return None
        parent = Path(row['path']).parent
        if fkey(parent) == fkey(self.root):
            return None
        self.expanded.discard(fkey(parent))
        return fkey(parent)

    def open_any(self, row):
        """`o` opens any folder as a project; enter only opens repos."""
        path = row['path']
        if row['kind'] == 'repo':
            return open_result(path, get_branch(path), path)
        return open_result(path)
