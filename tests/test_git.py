import pytest
from conftest import git

from cmdk_git import GitError, create_worktree, get_branch, get_repo_root, get_toplevel, get_worktrees


def test_single_worktree(repo):
    wts = get_worktrees(repo)
    assert len(wts) == 1
    assert wts[0]['branch'] == 'main'
    assert get_repo_root(repo) == str(repo.resolve())
    assert get_toplevel(repo / 'sub') is None  # missing dir: no crash, no result
    assert get_branch(repo) == 'main'


def test_outside_repo(tmp_path):
    assert get_worktrees(tmp_path) == []
    assert get_repo_root(tmp_path) is None
    assert get_branch(tmp_path) is None


def test_worktrees_include_linked_and_skip_bare(repo):
    git('worktree', 'add', '-q', str(repo.parent / 'wt-feature'), '-b', 'feature', cwd=repo)
    wts = get_worktrees(repo)
    assert [w['branch'] for w in wts] == ['main', 'feature']
    # repo root is the main worktree even when asked from a linked one
    assert get_repo_root(repo.parent / 'wt-feature') == str(repo.resolve())
    assert get_toplevel(repo.parent / 'wt-feature') == str((repo.parent / 'wt-feature').resolve())


def test_repo_root_inside_submodule_is_the_submodule_checkout(repo, tmp_path):
    src = tmp_path / 'sub-src'
    src.mkdir()
    git('init', '-q', '-b', 'main', cwd=src)
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init', cwd=src)
    git('-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(src), 'sub', cwd=repo)
    sub = str((repo / 'sub').resolve())
    assert get_repo_root(repo / 'sub') == sub
    assert get_repo_root(repo) == str(repo.resolve())
    assert [w['path'] for w in get_worktrees(repo / 'sub')] == [sub]   # not .git/modules/sub


def test_repo_root_of_bare_repo_worktree(repo, tmp_path):
    bare = tmp_path / 'proj.git'
    git('clone', '-q', '--bare', str(repo), str(bare), cwd=tmp_path)
    git('worktree', 'add', '-q', str(tmp_path / 'proj-main'), 'main', cwd=bare)
    assert get_repo_root(tmp_path / 'proj-main') == str(bare)
    assert [w['branch'] for w in get_worktrees(tmp_path / 'proj-main')] == ['main']   # bare entry dropped


def test_create_worktree_new_branch(repo):
    path = create_worktree(str(repo), 'feature/login')
    assert path == str(repo.parent / 'feature-login')   # slash becomes a dash in the dir name
    assert get_branch(path) == 'feature/login'
    assert len(get_worktrees(repo)) == 2


def test_create_worktree_existing_branch_is_checked_out(repo):
    git('branch', 'existing', cwd=repo)
    path = create_worktree(str(repo), 'existing')
    assert get_branch(path) == 'existing'


def test_create_worktree_normalises_whitespace(repo):
    path = create_worktree(str(repo), '  my  branch ')
    assert path.endswith('/my-branch')
    assert get_branch(path) == 'my-branch'


@pytest.mark.parametrize('bad', ['', '   ', '-rf', 'a..b', 'x~y', 'sp^ace'])
def test_create_worktree_rejects_bad_names(repo, bad):
    with pytest.raises(GitError):
        create_worktree(str(repo), bad)


def test_create_worktree_refuses_existing_dir(repo):
    (repo.parent / 'taken').mkdir()
    with pytest.raises(GitError, match='already exists'):
        create_worktree(str(repo), 'taken')


def test_create_worktree_surfaces_git_error(repo):
    # 'main' is already checked out in the main worktree: git refuses, and we relay its reason
    with pytest.raises(GitError, match='main'):
        create_worktree(str(repo), 'main')
