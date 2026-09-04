"""Run `git log` once and parse it into commits with per-file status and line counts.

One log pass with `--raw --numstat -M` gives both the A/M/D/R status per path and the
number of lines a deletion removed, so we never shell out per file.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

RS = "\x1e"  # record separator between commits
US = "\x1f"  # unit separator between header fields

FORMAT = f"{RS}%H{US}%at{US}%an{US}%s"


class GitError(RuntimeError):
    """git itself failed. Message carries git's stderr."""


@dataclass(frozen=True)
class Change:
    status: str  # single letter: A M D R C T U X
    path: str  # path after the change (new name for renames/copies)
    old_path: str | None = None  # only set for R and C


@dataclass
class Commit:
    sha: str
    ts: int
    author: str
    subject: str
    changes: list[Change] = field(default_factory=list)
    # path -> lines removed in this commit. None means git reported binary ("-").
    deleted_lines: dict[str, int | None] = field(default_factory=dict)


def unquote(path: str) -> str:
    """Undo git's C-style path quoting (core.quotePath). Plain paths pass through."""
    if len(path) < 2 or path[0] != '"' or path[-1] != '"':
        return path
    body = path[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.extend(ch.encode("utf-8"))
            i += 1
            continue
        i += 1
        esc = body[i]
        if esc in "01234567":
            out.append(int(body[i : i + 3], 8))
            i += 3
            continue
        simple = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
        out.extend(simple.get(esc, esc).encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="surrogateescape")


def _parse_raw_line(line: str) -> Change:
    # ":100644 000000 2aed677 0000000 D\tpath" or "... R100\told\tnew"
    meta, *paths = line.split("\t")
    status_token = meta.split(" ")[-1]
    status = status_token[0]
    paths = [unquote(p) for p in paths]
    if status in ("R", "C"):
        return Change(status, paths[1], old_path=paths[0])
    return Change(status, paths[0])


def _parse_numstat_line(line: str) -> tuple[str, int | None]:
    added, deleted, path = line.split("\t", 2)
    count = None if deleted == "-" else int(deleted)
    return unquote(path), count


def parse_log(text: str) -> list[Commit]:
    commits: list[Commit] = []
    for record in text.split(RS):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        sha, ts, author, subject = header.split(US, 3)
        commit = Commit(sha=sha, ts=int(ts), author=author, subject=subject)
        for line in body.splitlines():
            if not line:
                continue
            if line.startswith(":"):
                commit.changes.append(_parse_raw_line(line))
            elif "\t" in line:
                path, count = _parse_numstat_line(line)
                commit.deleted_lines[path] = count
        commits.append(commit)
    return commits


def read_log(repo: Path, all_refs: bool = False) -> list[Commit]:
    """Oldest-first commit list for `repo`, HEAD only unless `all_refs`."""
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        "--reverse",
        "--raw",
        "--numstat",
        "-M",
        "--no-color",
        f"--format={FORMAT}",
    ]
    if all_refs:
        cmd.append("--all")
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="surrogateescape")
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git exited {proc.returncode}")
    return parse_log(proc.stdout)
