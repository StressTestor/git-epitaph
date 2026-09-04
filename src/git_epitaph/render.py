"""Three ways to look at the graveyard: ASCII stones, a flat list, or JSON."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone

from git_epitaph.cause import cause_of_death
from git_epitaph.walk import Grave

INNER = 21  # characters of text per stone line
STONE_W = INNER + 8  # full rendered width of one stone column
GAP = 2
UNKNOWN_DATE = "????-??-??"


def iso(ts: int | None) -> str:
    if ts is None:
        return UNKNOWN_DATE
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def fit_path(path: str, width: int) -> str:
    """Keep the tail of a path, which is the part people recognise."""
    if len(path) <= width:
        return path
    return "…" + path[-(width - 1) :]


def _lines_label(lines: int | None) -> str:
    if lines is None:
        return "binary"
    return f"{lines} line{'s' if lines != 1 else ''}"


def _stone(g: Grave) -> list[str]:
    def body(text: str = "") -> str:
        return "  | " + text.center(INNER) + " |  "

    rows = [
        "   ." + "-" * INNER + ".   ",
        "  /" + " " * (INNER + 2) + "\\  ",
        body("R.I.P."),
        body("(RISEN)") if g.risen else body(),
        body(fit_path(g.path, INNER)),
        body(_lines_label(g.lines)),
        body(),
        body(iso(g.born)),
        body(iso(g.died)),
        body(),
    ]
    cause = textwrap.wrap(cause_of_death(g.epitaph), INNER)[:2] or [""]
    rows.extend(body(line) for line in cause)
    while len(rows) < 12:
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
        height = max(len(s) for s in row)
        for s in row:
            s.extend([" " * STONE_W] * (height - len(s)))
        for i in range(height):
            out.append((" " * GAP).join(s[i] for s in row))
        out.append("")
    return "\n".join(out).rstrip("\n")


def _sh_quote(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def render_list(graves: list[Grave]) -> str:
    blocks: list[str] = []
    for g in graves:
        head = g.path
        if g.aliases:
            head += f"  (born as {g.born_path})"
        if g.risen:
            head += "  [risen]"
        age = f"{g.age_days} days" if g.age_days is not None else "age unknown"
        short = g.died_sha[:12]
        blocks.append(
            "\n".join(
                [
                    head,
                    f"  {iso(g.born)} -> {iso(g.died)}  {age}  {_lines_label(g.lines)}  "
                    f"{cause_of_death(g.epitaph)}",
                    f"  killed by {g.killer} in {short}: {g.epitaph}",
                    f"  git checkout {short}^ -- {_sh_quote(g.path)}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _as_dict(g: Grave) -> dict:
    return {
        "path": g.path,
        "born_path": g.born_path,
        "aliases": g.aliases,
        "born": g.born,
        "born_iso": None if g.born is None else iso(g.born),
        "born_sha": g.born_sha,
        "died": g.died,
        "died_iso": iso(g.died),
        "died_sha": g.died_sha,
        "killer": g.killer,
        "epitaph": g.epitaph,
        "cause": cause_of_death(g.epitaph),
        "lines": g.lines,
        "age_days": g.age_days,
        "risen": g.risen,
    }


def to_json(graves: list[Grave]) -> str:
    return json.dumps([_as_dict(g) for g in graves], indent=2, ensure_ascii=False)


def summary(graves: list[Grave]) -> str:
    risen = sum(1 for g in graves if g.risen)
    lines = sum(g.lines or 0 for g in graves)
    return f"{len(graves)} buried, {risen} risen, {lines} lines lost"
