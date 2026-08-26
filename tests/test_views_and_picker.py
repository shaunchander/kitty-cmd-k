from pathlib import Path

import pytest
from conftest import git

from cmdk_picker import CreateError, Prompt, filter_rows, match_score
from cmdk_views import ProjectsView, WorktreeView, fkey


# ── matching / prompt ────────────────────────────────────────────────────


def test_match_score_tiers():
    assert match_score('', 'anything') == 2
    assert match_score('ron', 'chrono') == 2
    assert match_score('chn', 'chrono') == 1
    assert match_score('xyz', 'chrono') == 0


def test_filter_rows_substring_first_then_original_order():
    rows = [{'l': 'ab-cd'}, {'l': 'acd'}, {'l': 'zzz'}, {'l': 'xacdx'}]
    assert [r['l'] for r in filter_rows(rows, 'acd', lambda r: r['l'])] == ['acd', 'xacdx', 'ab-cd']


def test_prompt_feed():
    p = Prompt('Name: ')
    assert p.feed('enter') is None            # empty: ignored
    for ch in 'ab':
        p.feed(ch)
    p.feed('backspace')
    assert p.text == 'a'
    p.error = 'x'
    p.feed('b')
    assert p.error is None                    # typing clears the error
    assert p.feed('[') is None and p.text == 'ab['   # brackets are text here, not view switches
    assert p.feed('enter') == 'submit'
    assert p.feed('escape') == 'cancel'


# ── fs identity ──────────────────────────────────────────────────────────


def test_fkey_ignores_spelling(tmp_path):
    d = tmp_path / 'Dir'
    d.mkdir()
    (tmp_path / 'link').symlink_to(d)
    assert fkey(d) == fkey(tmp_path / 'link') == fkey(tmp_path / 'link' / '.' / '..' / 'Dir')
    assert fkey(tmp_path / 'missing') == str(tmp_path / 'missing')


# ── WorktreeView ─────────────────────────────────────────────────────────


def test_worktree_view_marks_current_and_creates(repo):
    git('worktree', 'add', '-q', str(repo.parent / 'wt-b'), '-b', 'b', cwd=repo)
    view = WorktreeView(str(repo.parent / 'wt-b'))
    assert view.available and view.can_create
    rows = view.rows('')
    assert [r['branch'] for r in rows] == ['main', 'b']
    assert [r['current'] for r in rows] == [False, True]
    assert view.activate(rows[0]) == {'path': rows[0]['path'], 'branch': 'main', 'repo_root': str(repo.resolve())}
    assert '*' in view.render(rows[1], 80) and '*' not in view.render(rows[0], 80)

    created = view.create('c')
    assert created['branch'] == 'c' and created['repo_root'] == str(repo.resolve())
    with pytest.raises(CreateError, match='already exists'):
        view.create('c')


def test_worktree_view_outside_repo(tmp_path):
    view = WorktreeView(str(tmp_path))
    assert not view.available and not view.can_create
    assert view.rows('') == []


# ── ProjectsView ─────────────────────────────────────────────────────────


@pytest.fixture
def tree(tmp_path):
    """root/{apps/{web(repo), api(repo)}, docs/, tools/{cli(repo)}} plus a hidden dir."""
    root = tmp_path / 'root'
    for rel in ['apps/web', 'apps/api', 'docs', 'tools/cli', '.hidden']:
        (root / rel).mkdir(parents=True)
    for rel in ['apps/web', 'apps/api', 'tools/cli']:
        git('init', '-q', cwd=root / rel)
    return root


def test_projects_tree_fold_and_select(tree):
    view = ProjectsView(str(tree), tree)            # cwd is the root: nothing pre-expanded
    assert view.available and view.initial_key is None
    assert [(r['depth'], r['kind'], r['name']) for r in view.rows('')] == [
        (0, 'folder', 'apps'), (0, 'folder', 'docs'), (0, 'folder', 'tools')]

    apps = view.rows('')[0]
    assert view.activate(apps) is None              # enter on a folder toggles
    rows = view.rows('')
    assert [r['name'] for r in rows] == ['apps', 'api', 'web', 'docs', 'tools']
    assert rows[1]['depth'] == 1 and rows[1]['kind'] == 'repo'

    # h on a child of an open folder collapses the parent and asks to select it
    assert view.toggle(rows[1], 'left') == apps['key']
    assert [r['name'] for r in view.rows('')] == ['apps', 'docs', 'tools']
    # h on a top-level row is a no-op
    assert view.toggle(view.rows('')[0], 'left') is None
    # l on a repo does nothing
    view.toggle(rows[1], 'right')
    assert len(view.rows('')) == 3


def test_projects_expand_to_cwd_stops_at_repo(tree):
    inside = tree / 'apps' / 'web' / 'src' / 'deep'
    inside.mkdir(parents=True)
    view = ProjectsView(str(inside), tree)
    rows = view.rows('')
    selected = next(r for r in rows if r['key'] == view.initial_key)
    assert selected['name'] == 'web' and selected['kind'] == 'repo'
    assert fkey(tree / 'apps') in view.expanded
    assert fkey(tree / 'apps' / 'web') not in view.expanded


def test_projects_search_is_flat_recursive_and_fuzzy(tree):
    view = ProjectsView(str(tree), tree)
    assert [r['label'] for r in view.rows('cli')] == ['tools/cli']
    assert [r['label'] for r in view.rows('ap')] == ['apps/api', 'apps/web']
    assert [r['label'] for r in view.rows('apweb')] == ['apps/web']     # fuzzy subsequence
    assert view.rows('zzz') == []


def test_projects_open_any_and_unavailable(tree, tmp_path):
    view = ProjectsView(str(tree), tree)
    rows = view.rows('')
    assert view.open_any(rows[1]) == {'path': str(tree / 'docs'), 'branch': None, 'repo_root': None}
    web = view.rows('web')[0]
    assert view.activate(web)['repo_root'] == str(tree / 'apps' / 'web')

    missing = ProjectsView(str(tree), tmp_path / 'nope')
    assert not missing.available and '--projects' in missing.empty_message()
