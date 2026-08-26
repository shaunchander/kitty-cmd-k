<h1 align="center">⌘K kitty-cmd-k</h1>
<p align="center">One <code>cmd+k</code> for kitty: jump to any git worktree or project and open it in your IDE layout.</p>

- ✅ one picker, two views — the git worktrees of the repo you're in, and a tree of your projects
- ✅ vim keys: `j`/`k`, `gg`/`G`, `ctrl+d`/`ctrl+u`, `/` to filter, `[` `]` to switch views
- ✅ `n` creates a new worktree without leaving the picker
- ✅ opens a tab with your layout, or focuses it if it's already open
- ✅ layouts in kitty's own session syntax, per repo or centralized
- ✅ zero dependencies — kitty's bundled Python and git

## Getting started

Clone into your kitty config directory:

```bash
git clone https://github.com/shaunchander/kitty-cmd-k ~/.config/kitty/kitty-cmd-k
```

Add a keybinding to `kitty.conf` (`--projects` is where the Projects view starts; it defaults to `~`):

```conf
map cmd+k kitten kitty-cmd-k/cmd_k.py --projects ~/code
```

On Linux, `ctrl+shift+k` or any other key works the same way. Reload kitty's config (`ctrl+shift+f5`) and press the key.

🎉 Inside a git repo the picker opens on **Worktrees**; anywhere else it opens on **Projects**. Pick something and kitty opens a tab for it — a single shell until you configure a layout.

## Keys

| Key | Action |
|---|---|
| `[` / `]` | previous / next view |
| `j` / `k` | move down / up (also `ctrl+n` / `ctrl+p`, arrows) |
| `gg` / `G` | jump to top / bottom |
| `ctrl+d` / `ctrl+u` | half page down / up |
| `h` / `l` | collapse / expand a folder (Projects); `h` on a collapsed row jumps to its parent |
| `enter` | open a worktree or repo; toggle a folder |
| `o` | open the selected folder as a project even if it isn't a git repo |
| `n` | create a new worktree (Worktrees view) — a sibling directory checked out on a new branch |
| `/` | filter; `esc` returns to normal mode and keeps the filter |
| `esc` / `q` | clear the filter, then close |

In Projects, filtering switches from the tree to a flat fuzzy search over every repo under `--projects`, so `/chn` finds `work/chrono`.

## Configuration

Without any config, opening something gives you a tab named `{repo} ({basename})` with one shell. To get a real layout, kitty-cmd-k looks for config in this order and uses the first hit:

1. `.kitty-cmd-k.toml` in the worktree or project directory
2. `.kitty-cmd-k.toml` in the repo root (so all worktrees of a repo share it)
3. `~/.config/kitty/cmd-k.toml` — the first `[[sessions]]` entry whose `match` regex hits the path
4. `~/.config/kitty/cmd-k.toml` — `[default]`

Each of those describes one tab, either by pointing at a **session file** or with **inline panes**. See [`examples/`](examples/) for complete files.

### Session files (recommended)

```toml
# .kitty-cmd-k.toml
session_file = ".kitty/ide.conf"        # relative to this file, or absolute / ~-prefixed
```

```conf
# .kitty/ide.conf — kitty's session syntax
new_tab {repo} ({branch})
layout splits
cd {path}
launch --title editor zsh -i -c "nvim; exec zsh"
launch --title shell --location=hsplit zsh
```

`launch` lines are passed to kitty's [`launch`](https://sw.kovidgoyal.net/kitty/launch/) as-is, so anything it accepts works (`--location`, `--title`, `--env`, `--cwd`, …). Running commands through `zsh -i -c` loads your shell init first — useful when the editor needs a `PATH`, a virtualenv or `direnv`. A session file may contain several `new_tab` blocks; each becomes a tab.

Only `new_tab`, `layout`, `cd` and `launch` are honoured. Other session directives (`focus`, `new_os_window`, `os_window_*`, …) are ignored.

### Inline panes

```toml
tab_title = "{repo} ({branch})"
layout = "tall"

[[panes]]
title = "editor"
command = "nvim"

[[panes]]
title = "tests"
location = "vsplit"        # first pane creates the tab; later panes split it
command = "npm test -- --watch"

[[panes]]
title = "shell"
location = "hsplit"
cwd = "{path}/packages/app"   # defaults to the worktree / project path
```

### Central config

```toml
# ~/.config/kitty/cmd-k.toml
[[sessions]]
match = "-api$"                              # regex against the full path
session_file = "sessions/backend.conf"       # relative to this file

[[sessions]]
match = "-ui$"
session_file = "sessions/frontend.conf"

[default]
session_file = "sessions/ide.conf"
```

### Template variables

Available in `tab_title`, `session_file` contents, pane `title` / `command` / `cwd`:

| Variable | Value |
|---|---|
| `{branch}` | checked-out branch (empty for a plain folder) |
| `{repo}` | repository name (the main worktree's directory) |
| `{path}` | full path of the worktree / project |
| `{basename}` | its directory name |
| `{FOLDER_NAME}`, `{PROJECT_DIR}` | aliases of `{basename}` and `{path}` |

Tabs are matched **by title** to decide whether to focus an existing one, so make titles unique per worktree — `{basename}` or `{branch}` in `tab_title` / `new_tab` does it.

## Turn kitty into an IDE

kitty already has splits, tabs, and a `launch` command; kitty-cmd-k adds the "open project" gesture. A layout like [`examples/ide.conf`](examples/ide.conf) — editor on the left, an AI assistant and a shell stacked on the right — plus `[default] session_file = ...` in `cmd-k.toml` means every repo and worktree opens the same way with one key:

```
┌──────────────┬──────────────┐
│              │  assistant   │
│    editor    ├──────────────┤
│              │    shell     │
└──────────────┴──────────────┘
```

Pair it with a kitten that forwards `ctrl+h/j/k/l` to your editor (e.g. [vim-kitty-navigator](https://github.com/knubie/vim-kitty-navigator)) and `map cmd+j toggle_layout stack` to maximize a pane, and the rest of an IDE falls out of kitty's own config.

## How it works

kitty calls two functions at different times. `main()` runs in an overlay window over your current tab — that's the picker — and returns a JSON list of tabs to open. `handle_result()` then runs inside kitty's own process and turns that into `launch` / `goto-layout` calls through kitty's in-process remote-control API. That's why `allow_remote_control` does **not** need to be enabled.

The kitten is split into small modules (`cmdk_picker.py` for the terminal UI and `View` contract, `cmdk_views.py` for the two views, `cmdk_git.py`, `cmdk_session.py`); kitty puts the kitten's directory on `sys.path`, so a clone or a symlink of the whole directory both work. Adding a third view is a `View` subclass and one line in `cmd_k.main()`.

## Requirements

- [kitty](https://sw.kovidgoyal.net/kitty/) 0.31 or newer (bundles Python 3.11, needed for `tomllib`)
- git

## Development

```bash
python3 -m pytest              # unit + pty-driven picker tests, no kitty needed
CMDK_E2E=1 python3 -m pytest tests/test_kitty_e2e.py   # opens a throwaway kitty and drives the real kitten
```

## License

MIT
