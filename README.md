<h1 align="center">⌘K kitty-cmd-k</h1>
<p align="center">One <code>cmd+k</code> for kitty: jump to any git worktree or project and open it in your layout.</p>

- ✅ one picker, two views — the git worktrees of the repo you're in, and a tree of your projects
- ✅ vim keys: `j`/`k`, `gg`/`G`, `ctrl+d`/`ctrl+u`, `/` to filter, `[` `]` to switch views
- ✅ `n` creates a new worktree without leaving the picker
- ✅ opens a tab with your layout, or focuses it if it's already open
- ✅ layouts in kitty's own session syntax, per repo or centralized
- ✅ zero dependencies — kitty's bundled Python and git

## Install

```bash
git clone https://github.com/shaunchander/kitty-cmd-k ~/.config/kitty/kitty-cmd-k
```

```conf
# kitty.conf
map cmd+k kitten kitty-cmd-k/cmd_k.py --projects ~/code
```

Reload kitty (`ctrl+shift+f5`) and press `cmd+k`. Inside a git repo the picker opens on **Worktrees**; anywhere else it opens on **Projects**.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--projects <dir>` | `~` | root of the Projects view |

## Keys

| Key | Action |
|---|---|
| `[` / `]` | previous / next view |
| `j` / `k` | move down / up (also `ctrl+n` / `ctrl+p`, arrows) |
| `gg` / `G` | top / bottom |
| `ctrl+d` / `ctrl+u` | half page down / up |
| `h` / `l` | collapse / expand a folder (Projects) |
| `enter` | open a worktree or repo; toggle a folder |
| `o` | open the selected folder even if it isn't a git repo |
| `n` | create a new worktree (Worktrees) — a sibling directory on a new branch |
| `/` | filter; `esc` keeps the filter and returns to normal mode |
| `esc` / `q` | clear the filter, then close |

## Configuration

With no config, opening something gives you a tab named `{repo} ({basename})` with one shell. Layouts are looked up in this order; the first hit wins:

1. `.kitty-cmd-k.toml` in the worktree or project directory
2. `.kitty-cmd-k.toml` in the repo root (shared by all its worktrees)
3. `~/.config/kitty/cmd-k.toml` — first `[[sessions]]` whose `match` regex hits the path
4. `~/.config/kitty/cmd-k.toml` — `[default]`

A config describes one tab, either with a `session_file` or with inline `[[panes]]`. Complete files are in [`examples/`](examples/).

### Session file

```toml
# .kitty-cmd-k.toml
session_file = ".kitty/ide.conf"   # relative to this file, or absolute / ~
```

```conf
# .kitty/ide.conf — kitty session syntax
new_tab {repo} ({branch})
layout splits
cd {path}
launch --title editor zsh -i -c "nvim; exec zsh"
launch --title shell --location=hsplit zsh
```

`launch` lines are passed to kitty's [`launch`](https://sw.kovidgoyal.net/kitty/launch/) unchanged, so `--location`, `--title`, `--env`, `--cwd`, … all work. Several `new_tab` blocks make several tabs. Only `new_tab`, `layout`, `cd` and `launch` are read; other session directives are ignored.

### Inline panes

```toml
# .kitty-cmd-k.toml
tab_title = "{repo} ({branch})"
layout = "tall"

[[panes]]
title = "editor"
command = "nvim"

[[panes]]
title = "tests"
location = "vsplit"            # first pane creates the tab; later panes split it
command = "npm test -- --watch"

[[panes]]
title = "shell"
location = "hsplit"
cwd = "{path}/packages/app"    # defaults to the worktree / project path
```

| Key | Meaning |
|---|---|
| `tab_title` | tab name, default `{repo} ({basename})` |
| `layout` | kitty layout for the tab, default `splits` |
| `panes[].title` | window title |
| `panes[].command` | command to run; empty for a shell |
| `panes[].location` | `hsplit` / `vsplit` (ignored on the first pane) |
| `panes[].cwd` | working directory |

### Central config

```toml
# ~/.config/kitty/cmd-k.toml
[[sessions]]
match = "-api$"                          # regex against the full path
session_file = "sessions/backend.conf"   # relative to this file

[[sessions]]
match = "-ui$"
session_file = "sessions/frontend.conf"

[default]
session_file = "sessions/ide.conf"
```

### Template variables

Usable in `tab_title`, session files and pane `title` / `command` / `cwd`:

| Variable | Value |
|---|---|
| `{branch}` | checked-out branch (empty for a plain folder) |
| `{repo}` | repository name |
| `{path}` | full path of the worktree / project |
| `{basename}` | its directory name |
| `{FOLDER_NAME}`, `{PROJECT_DIR}` | aliases of `{basename}` and `{path}` |

Tabs are matched by title to decide whether to focus an existing one, so keep `{basename}` or `{branch}` in the title.

## Requirements

- [kitty](https://sw.kovidgoyal.net/kitty/) 0.31 or newer
- git

## Development

```bash
python3 -m pytest                                        # unit + pty tests
CMDK_E2E=1 python3 -m pytest tests/test_kitty_e2e.py    # drives a throwaway kitty
```

## License

MIT
