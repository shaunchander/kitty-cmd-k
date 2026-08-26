"""Git plumbing for kitty-cmd-k.

Stdlib only, no imports from the other cmdk_* modules, so this file can be
tested against a throwaway `git init` repo with nothing else loaded.
"""

import subprocess
from pathlib import Path


class GitError(Exception):
    """A git command failed. str(err) is a one-line, user-facing reason."""


def _git(args, cwd=None, timeout=5):
    """Run git and return the CompletedProcess, or None if git could not be run at all."""
    try:
        return subprocess.run(
            ['git', *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def run_git(args, cwd=None):
    """stdout on success, None on any failure (missing git, timeout, non-zero exit)."""
    result = _git(args, cwd=cwd)
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def get_worktrees(cwd):
    """Worktrees of the repo containing cwd, as dicts with 'path' and 'branch'. Bare entries are dropped."""
    out = run_git(['worktree', 'list', '--porcelain'], cwd=cwd)
    if not out:
        return []
    worktrees, current = [], {}
    for line in out.splitlines():
        if line.startswith('worktree '):
            if current:
                worktrees.append(current)
            current = {'path': line[9:]}
        elif line.startswith('branch '):
            current['branch'] = line[7:].removeprefix('refs/heads/')
        elif line == 'bare':
            current['bare'] = True
        elif line == 'detached':
            current['branch'] = '(detached)'
    if current:
        worktrees.append(current)
    # The main worktree comes first. Inside a submodule git prints its gitdir
    # (.git/modules/<name>) there instead of the checkout; use the real root.
    if worktrees and not worktrees[0].get('bare'):
        root = get_repo_root(cwd)
        if root:
            worktrees[0]['path'] = root
    return [w for w in worktrees if not w.get('bare')]


def get_repo_root(cwd):
    """The main worktree (or the bare repo directory), or None outside a repo.

    The common git dir is <root>/.git for ordinary repos and worktrees. For a
    submodule it is <superproject>/.git/modules/<name>, whose config records the
    checkout in core.worktree; for a bare repo it is the repo directory itself.
    """
    out = run_git(['rev-parse', '--git-common-dir'], cwd=cwd)
    if not out:
        return None
    common = (Path(cwd) / out.strip()).resolve()
    if common.name == '.git':
        return str(common.parent)
    worktree = run_git([f'--git-dir={common}', 'config', '--get', 'core.worktree'])
    if worktree:
        return str((common / worktree.strip()).resolve())
    return str(common)


def get_toplevel(cwd):
    """Root of the worktree containing cwd, or None outside a repo."""
    out = run_git(['rev-parse', '--show-toplevel'], cwd=cwd)
    return out.strip() if out else None


def get_branch(path):
    out = run_git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd=path)
    return out.strip() if out else None


def create_worktree(repo_root, name):
    """Create a worktree next to repo_root on branch `name`; return its path.

    The directory is a sibling of repo_root named after the branch, with any
    '/' replaced by '-' (so `feature/login` lives at `../feature-login`).
    The branch is created if it does not exist, otherwise it is checked out.
    Raises GitError with a one-line reason on any failure.
    """
    name = '-'.join(name.split())
    if not name:
        raise GitError('name is empty')
    if name.startswith('-'):
        raise GitError('name cannot start with "-"')
    if run_git(['check-ref-format', '--branch', name], cwd=repo_root) is None:
        raise GitError(f'"{name}" is not a valid branch name')

    dest = Path(repo_root).parent / name.replace('/', '-')
    if dest.exists():
        raise GitError(f'{dest.name} already exists next to the repo')

    result = _git(['worktree', 'add', str(dest), '-b', name], cwd=repo_root, timeout=60)
    if result is not None and result.returncode != 0 and 'already exists' in result.stderr:
        # The branch exists: check it out instead of creating it.
        result = _git(['worktree', 'add', str(dest), name], cwd=repo_root, timeout=60)
    if result is None:
        raise GitError('git is not available')
    if result.returncode != 0:
        lines = [l for l in result.stderr.strip().splitlines() if l.strip()]
        raise GitError(lines[-1].removeprefix('fatal: ') if lines else 'git worktree add failed')
    return str(dest)
