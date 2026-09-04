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

# %ct (committer time) is monotonic along a first-parent chain in practice; author time is
# whatever the contributor's clock said and produces negative ages.
FORMAT = f"{RS}%H{US}%ct{US}%an{US}%s"


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


def run_git(repo: Path, *args: str) -> tuple[str, str]:
    """Run git in `repo`; return (stdout, stderr). Raises GitError on failure or no git."""
    cmd = ["git", "-C", str(repo), *args]
    try:
        # git emits UTF-8 regardless of locale; the locale codec is wrong under latin-1.
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape"
        )
    except FileNotFoundError as exc:
        raise GitError("git not found on PATH") from exc
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git exited {proc.returncode}")
    return proc.stdout, proc.stderr


def read_log(
    repo: Path, all_refs: bool = False, count_lines: bool = True
) -> tuple[list[Commit], str]:
    """Oldest-first mainline history for `repo` plus git's warnings (e.g. rename limit hit).

    `--first-parent` makes the walk a straight line, so a birth is always an ancestor of
    its death and two branches adding the same path can never interleave. Each merge is
    diffed against its first parent, so a PR lands as one net change at the merge commit,
    and files created or kept inside a conflict resolution are visible.

    `--numstat` is ~95% of the wall time on large repos (it reads every deleted blob), so
    callers that only need counts for a handful of graves pass `count_lines=False` and
    fill them in afterwards with `deleted_lines_in`.
    """
    args = [
        "log",
        "--reverse",
        "--first-parent",
        "--diff-merges=first-parent",
        "--raw",
        "-M",
        "--no-color",
        f"--format={FORMAT}",
    ]
    if count_lines:
        args.insert(args.index("--raw") + 1, "--numstat")
    if all_refs:
        args.append("--all")
    out, err = run_git(repo, *args)
    return parse_log(out), err.strip()


def deleted_lines_in(repo: Path, sha: str, paths: list[str]) -> dict[str, int | None]:
    """Lines removed from each of `paths` by commit `sha`, against its first parent."""
    out, _ = run_git(
        repo, "diff-tree", "-r", "--numstat", "--no-color", f"{sha}^1", sha, "--", *paths
    )
    result: dict[str, int | None] = {}
    for line in out.splitlines():
        if "\t" in line:
            path, count = _parse_numstat_line(line)
            result[path] = count
    return result


def living_paths(repo: Path, all_refs: bool = False) -> set[str]:
    """Paths that exist at the tip of the walked history (HEAD, or every ref with --all)."""
    if all_refs:
        out, _ = run_git(repo, "for-each-ref", "--format=%(objectname)")
        refs = out.split()
    else:
        refs = ["HEAD"]
    paths: set[str] = set()
    for ref in refs:
        out, _ = run_git(repo, "ls-tree", "-r", "-z", "--name-only", ref)
        paths.update(p for p in out.split("\0") if p)
    return paths
