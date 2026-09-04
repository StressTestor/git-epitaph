"""Three ways to look at the graveyard: ASCII stones, a flat list, or JSON."""

from __future__ import annotations

import json
import textwrap
import unicodedata
from datetime import datetime, timezone

from git_epitaph.cause import cause_of_death
from git_epitaph.walk import Grave

INNER = 21  # display cells of text per stone line
STONE_W = INNER + 8  # full rendered width of one stone column
STONE_ROWS = 13
GAP = 2
UNKNOWN_DATE = "????-??-??"


def clean(text: str) -> str:
    """Escape control characters so a hostile commit subject cannot drive the terminal.

    Lone surrogates (bytes git handed us that were not UTF-8) are not printable either,
    so they come out as `\\udcXX` instead of crashing `print`.
    """
    return "".join(ch if ch.isprintable() or ch == " " else repr(ch)[1:-1] for ch in text)


def cell_width(text: str) -> int:
    """Terminal cells a string occupies: wide/fullwidth glyphs take two, combining take zero."""
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def center(text: str, width: int) -> str:
    pad = max(0, width - cell_width(text))
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def iso(ts: int | None) -> str:
    if ts is None:
        return UNKNOWN_DATE
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def fit_path(path: str, width: int) -> str:
    """Keep the tail of a path, which is the part people recognise, within `width` cells."""
    if cell_width(path) <= width:
        return path
    tail = ""
    for ch in reversed(path):
        if cell_width(tail + ch) > width - 1:
            break
        tail = ch + tail
    return "…" + tail


def _lines_label(g: Grave) -> str:
    if not g.counted:
        return "lines not counted"
    if g.binary or g.lines is None:
        return "binary"
    return f"{g.lines} line{'s' if g.lines != 1 else ''}"


def _stone(g: Grave) -> list[str]:
    def body(text: str = "") -> str:
        return "  | " + center(text, INNER) + " |  "

    rows = [
        "   ." + "-" * INNER + ".   ",
        "  /" + " " * (INNER + 2) + "\\  ",
        body("R.I.P."),
        body("(RISEN)") if g.risen else body(),
        body(fit_path(clean(g.path), INNER)),
        body(_lines_label(g)),
        body(),
        body(iso(g.born)),
        body(iso(g.died)),
        body(),
    ]
    cause = textwrap.wrap(cause_of_death(g.epitaph), INNER)[:2] or [""]
    rows.extend(body(line) for line in cause)
    while len(rows) < STONE_ROWS - 1:
        rows.append(body())
    rows.append(" _|" + "_" * (INNER + 2) + "|_ ")
    return rows


def render_stones(graves: list[Grave], width: int = 80) -> str:
    if not graves:
        return ""
    cols = max(1, (width + GAP) // (STONE_W + GAP))
    out: list[str] = []
    for start in range(0, len(graves), cols):
        row = [_stone(g) for g in graves[start : start + cols]]
        for i in range(STONE_ROWS):
            out.append((" " * GAP).join(s[i] for s in row))
        out.append("")
    return "\n".join(out).rstrip("\n")


def _sh_quote(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def render_list(graves: list[Grave]) -> str:
    blocks: list[str] = []
    for g in graves:
        head = clean(g.path)
        if g.aliases:
            head += f"  (born as {clean(g.born_path)})"
        if g.risen:
            head += "  [risen]"
        if g.age_days is None:
            age = "age unknown"
        else:
            age = f"{g.age_days} day{'s' if g.age_days != 1 else ''}"
        short = g.died_sha[:12]
        blocks.append(
            "\n".join(
                [
                    head,
                    f"  {iso(g.born)} -> {iso(g.died)}  {age}  {_lines_label(g)}  "
                    f"{cause_of_death(g.epitaph)}",
                    f"  killed by {clean(g.killer)} in {short}: {clean(g.epitaph)}",
                    f"  git checkout {short}^ -- {_sh_quote(clean(g.path))}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _json_safe(text: str) -> str:
    """Lone surrogates from non-UTF-8 filenames become the original byte as `\\xNN`."""
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def _as_dict(g: Grave) -> dict:
    return {
        "path": _json_safe(g.path),
        "born_path": _json_safe(g.born_path),
        "aliases": [_json_safe(a) for a in g.aliases],
        "born": g.born,
        "born_iso": None if g.born is None else iso(g.born),
        "born_sha": g.born_sha,
        "died": g.died,
        "died_iso": iso(g.died),
        "died_sha": g.died_sha,
        "killer": _json_safe(g.killer),
        "epitaph": _json_safe(g.epitaph),
        "cause": cause_of_death(g.epitaph),
        "lines": g.lines,
        "binary": g.binary,
        "lines_counted": g.counted,
        "age_days": g.age_days,
        "risen": g.risen,
    }


def to_json(graves: list[Grave]) -> str:
    return json.dumps([_as_dict(g) for g in graves], indent=2, ensure_ascii=False)


def summary(graves: list[Grave]) -> str:
    risen = sum(1 for g in graves if g.risen)
    head = f"{len(graves)} buried, {risen} risen"
    if graves and all(g.counted for g in graves):
        head += f", {sum(g.lines or 0 for g in graves)} lines lost"
    return head
