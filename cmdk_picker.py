"""Terminal picker engine for kitty-cmd-k.

Owns the raw-mode terminal, the render loop, fuzzy filtering and the View
contract. Views know nothing about keys or drawing beyond `render(row)`.

To add a view, subclass `View` (see cmdk_views.py for two implementations)
and append an instance to the list passed to `run_picker`.

Keys handled here, identical for every view:

    [ / ]            previous / next view
    j / k            move            (also ctrl+n / ctrl+p, arrows)
    gg / G           top / bottom
    ctrl+d / ctrl+u  half page
    h / l            view.toggle(row, 'left' | 'right')   (also arrows, backspace)
    enter            view.activate(row)
    o                view.open_any(row)
    n                prompt, then view.create(text)   if view.can_create
    /                filter mode; esc returns to normal mode keeping the filter
    esc / q          clear the filter, then close
"""

import os
import select
import signal
import sys
import termios
import tty


class CreateError(Exception):
    """Raised by View.create(); the message is shown inline and the prompt stays open."""


class View:
    """Base class for a picker column. Override what you need; defaults are safe no-ops.

    Rows are plain dicts. The picker only reads an optional 'key' entry, used to
    keep the selection on the same row across re-renders (see initial_key and
    the return value of toggle()).
    """

    name = ''
    initial_key = None          # 'key' of the row to select when the picker opens
    can_create = False          # enables the `n` prompt
    create_prompt = 'Name: '

    @property
    def available(self):
        return True

    def subheader(self):
        """One dim line under the view tabs (e.g. the repo or root directory)."""
        return ''

    def empty_message(self):
        """Shown instead of rows when not available."""
        return ''

    def help(self):
        """Footer hint in normal mode."""
        return ''

    def rows(self, query):
        """Rows to show; `query` is the active filter ('' when none)."""
        return []

    def render(self, row, width):
        """Text for a row. May contain SGR codes; visible length must fit `width`."""
        return ''

    def activate(self, row):
        """Enter. Return a result dict to close the picker, or None to stay open."""
        return None

    def open_any(self, row):
        """`o`. Like activate but for rows that enter would only toggle."""
        return None

    def toggle(self, row, direction):
        """`h` / `l` as direction 'left' / 'right'. Return a row 'key' to move the selection there, else None."""
        return None

    def create(self, name):
        """`n` prompt submitted. Return a result dict, None to stay, or raise CreateError."""
        raise NotImplementedError


class Prompt:
    """Single-line text entry used by the `n` key. Reusable by any View.create()."""

    def __init__(self, label):
        self.label = label
        self.text = ''
        self.error = None

    def feed(self, key):
        """Returns 'submit', 'cancel' or None (still editing)."""
        if key == 'escape':
            return 'cancel'
        if key == 'enter':
            return 'submit' if self.text.strip() else None
        if key == 'backspace':
            self.text = self.text[:-1]
        elif len(key) == 1 and key.isprintable():
            self.text += key
        else:
            return None
        self.error = None
        return None


# ── Matching ─────────────────────────────────────────────────────────────


def match_score(query, text):
    """0 = no match, 2 = substring, 1 = subsequence (fuzzy)."""
    if not query:
        return 2
    q, t = query.lower(), text.lower()
    if q in t:
        return 2
    it = iter(t)
    return 1 if all(c in it for c in q) else 0


def filter_rows(rows, query, key):
    """Rows matching query, substring hits first, original order within a tier.

    `key` maps a row to its searchable text (unrelated to the row's 'key' entry).
    """
    scored = [(match_score(query, key(r)), i, r) for i, r in enumerate(rows)]
    return [r for s, _, r in sorted((x for x in scored if x[0]), key=lambda x: (-x[0], x[1]))]


# ── Terminal input ───────────────────────────────────────────────────────


_resized = False


def _on_resize(sig, frame):
    global _resized
    _resized = True


CONTROL = {
    '\r': 'enter', '\n': 'enter',
    '\x7f': 'backspace', '\x08': 'backspace',
    '\x03': 'escape',            # ctrl+c
    '\x04': 'half_down',         # ctrl+d
    '\x15': 'half_up',           # ctrl+u
    '\x0e': 'down',              # ctrl+n
    '\x10': 'up',                # ctrl+p
}
SEQUENCES = {
    '\x1b[A': 'up', '\x1b[B': 'down', '\x1b[C': 'right', '\x1b[D': 'left',
    '\x1bOA': 'up', '\x1bOB': 'down', '\x1bOC': 'right', '\x1bOD': 'left',
    '\x1b[H': 'home', '\x1b[F': 'end', '\x1b[1~': 'home', '\x1b[4~': 'end',
    '\x1b[5~': 'half_up', '\x1b[6~': 'half_down',
}


def _read_escape(fd):
    """ESC was just read: consume the rest of the sequence. Lone ESC is 'escape';
    unknown sequences (alt+key, delete, function keys) are 'unknown' and ignored."""
    seq = '\x1b'
    while len(seq) < 16:
        r, _, _ = select.select([fd], [], [], 0.03)
        if not r:
            break
        seq += os.read(fd, 1).decode('utf-8', errors='replace')
        if len(seq) == 2:
            if seq[1] not in '[O':          # alt+<key>: ESC followed by one char
                break
        elif seq[1] == 'O' or '\x40' <= seq[-1] <= '\x7e':   # SS3 has one char; CSI ends at 0x40-0x7e
            break
    if seq == '\x1b':
        return 'escape'
    return SEQUENCES.get(seq, 'unknown')


def read_key(fd):
    """Return a named key or the raw printable character. A resize surfaces as 'resize'."""
    global _resized
    while True:
        if _resized:
            _resized = False
            return 'resize'
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            break
    ch = os.read(fd, 1).decode('utf-8', errors='replace')
    if ch == '\x1b':
        return _read_escape(fd)
    return CONTROL.get(ch, ch)


# ── Rendering ────────────────────────────────────────────────────────────


def _draw(views, view_index, rows, selected, offset, body_height, width, height, query, mode, prompt):
    view = views[view_index]
    out = ['\033[2J\033[H']

    tabs = [f'\033[1;7m {v.name} \033[0m' if i == view_index else f'\033[2m {v.name} \033[0m'
            for i, v in enumerate(views)]
    out.append('  ' + ' '.join(tabs) + '\r\n')

    if mode == 'prompt':
        out.append(f'  \033[33m{prompt.label}\033[0m{prompt.text}\033[7m \033[0m\r\n')
    elif mode == 'search':
        out.append(f'  \033[33m/\033[0m {query}\033[7m \033[0m\r\n')
    elif query:
        out.append(f'  \033[2m/ {query}\033[0m\r\n')
    else:
        out.append(f'  \033[2m{view.subheader()[:width - 2]}\033[0m\r\n')
    out.append('\r\n')

    if not view.available:
        out.append(f'  \033[2m{view.empty_message()[:width - 2]}\033[0m\r\n')
    elif not rows:
        out.append('  \033[2m(no matches)\033[0m\r\n')
    else:
        for i in range(offset, min(len(rows), offset + body_height)):
            line = view.render(rows[i], width - 4)
            out.append(f'  \033[7m {line} \033[0m\r\n' if i == selected else f'   {line}\r\n')
        if len(rows) > body_height:
            out.append(f'  \033[2m{selected + 1}/{len(rows)}\033[0m')

    if mode == 'prompt':
        footer = f'\033[33m{prompt.error}\033[0m' if prompt.error else '\033[2menter confirm   esc cancel\033[0m'
    elif mode == 'search':
        footer = '\033[2mtype to filter   ctrl+n/p move   enter open   esc done\033[0m'
    else:
        footer = f'\033[2m{view.help()[:width - 2]}\033[0m'
    out.append(f'\033[{height};1H  {footer}')
    sys.stdout.write(''.join(out))
    sys.stdout.flush()


# ── Picker loop ──────────────────────────────────────────────────────────


def run_picker(views, start_index=0):
    """Drive the picker until a view returns a result dict (returned) or the user closes it (None)."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    prev_handler = signal.signal(signal.SIGWINCH, _on_resize)

    view_index = start_index % len(views)
    selected = offset = 0
    query = ''
    mode = 'normal'              # 'normal' | 'search' | 'prompt'
    prompt = None
    pending_g = False
    select_key = views[view_index].initial_key

    try:
        tty.setraw(fd)
        sys.stdout.write('\033[?25l\033[?1049h')

        while True:
            view = views[view_index]
            rows = view.rows(query) if view.available else []

            if select_key is not None:
                selected = next((i for i, r in enumerate(rows) if r.get('key') == select_key), selected)
                select_key = None
            selected = max(0, min(selected, len(rows) - 1))

            size = os.get_terminal_size()
            width, height = size.columns, size.lines
            body_height = max(1, height - 6)
            if selected < offset:
                offset = selected
            elif selected >= offset + body_height:
                offset = selected - body_height + 1
            offset = max(0, min(offset, max(0, len(rows) - body_height)))

            _draw(views, view_index, rows, selected=selected, offset=offset, body_height=body_height,
                  width=width, height=height, query=query, mode=mode, prompt=prompt)

            key = read_key(fd)
            row = rows[selected] if rows else None

            if key == 'resize':
                continue

            # ── prompt mode: every key belongs to the text field ──
            if mode == 'prompt':
                outcome = prompt.feed(key)
                if outcome == 'cancel':
                    mode, prompt = 'normal', None
                elif outcome == 'submit':
                    try:
                        result = view.create(prompt.text.strip())
                    except CreateError as e:
                        prompt.error = str(e)
                    else:
                        if result:
                            return result
                        mode, prompt = 'normal', None
                continue

            # ── keys shared by normal and search mode ──
            if key in (']', '['):
                view_index = (view_index + (1 if key == ']' else -1)) % len(views)
                selected, offset, pending_g = 0, 0, False
                select_key = views[view_index].initial_key
                continue
            if key == 'up':
                selected -= 1
            elif key == 'down':
                selected += 1
            elif key == 'half_down':
                selected += body_height // 2
            elif key == 'half_up':
                selected -= body_height // 2
            elif key == 'home':
                selected = 0
            elif key == 'end':
                selected = len(rows) - 1
            elif key == 'enter' and row is not None:
                result = view.activate(row)
                if result:
                    return result
                mode = 'normal'
            elif mode == 'search':
                if key == 'escape':
                    mode = 'normal'
                elif key == 'backspace':
                    query = query[:-1]
                elif len(key) == 1 and key.isprintable():
                    query += key
                    selected = 0
            # ── normal mode (vim) ──
            elif key == 'j':
                selected += 1
            elif key == 'k':
                selected -= 1
            elif key == '/':
                mode = 'search'
            elif key == 'g':
                if pending_g:
                    selected = 0
                pending_g = not pending_g
                continue
            elif key == 'G':
                selected = len(rows) - 1
            elif key in ('escape', 'q'):
                if query:
                    query, selected = '', 0
                else:
                    return None
            elif key in ('l', 'right') and row is not None:
                view.toggle(row, 'right')
            elif key in ('h', 'left', 'backspace') and row is not None:
                select_key = view.toggle(row, 'left')
            elif key == 'o' and row is not None:
                result = view.open_any(row)
                if result:
                    return result
            elif key == 'n' and view.can_create:
                mode, prompt = 'prompt', Prompt(view.create_prompt)
            pending_g = False
    finally:
        sys.stdout.write('\033[?1049l\033[?25h')
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        signal.signal(signal.SIGWINCH, prev_handler)
