"""`git epitaph`: walk a repo's history and print a tombstone for every deleted file."""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from git_epitaph import __version__
from git_epitaph.gitlog import GitError, deleted_lines_in, living_paths, read_log, run_git
from git_epitaph.render import render_list, render_stones, summary, to_json
from git_epitaph.walk import Grave, bury

SORT_KEYS = {
    "died": lambda g: g.died,
    "born": lambda g: g.born if g.born is not None else -1,
    "lines": lambda g: g.lines if g.lines is not None else -1,
    "age": lambda g: g.age_days if g.age_days is not None else -1,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="git epitaph",
        description="obituaries for every file your repo has ever deleted.",
    )
    p.add_argument("repo", nargs="?", default=".", help="path inside a git repo (default: .)")
    p.add_argument("--limit", "-n", type=_non_negative, default=None, help="show at most N graves")
    p.add_argument(
        "--sort",
        choices=sorted(SORT_KEYS),
        default="died",
        help="sort key, newest/largest first (default: died)",
    )
    p.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        type=_parse_since,
        default=None,
        help="only deaths on or after this date (UTC)",
    )
    p.add_argument("--path", metavar="GLOB", help="only paths matching this glob (any alias)")
    p.add_argument(
        "--style",
        choices=["auto", "stones", "list"],
        default="auto",
        help="stones when stdout is a terminal, list otherwise (default: auto)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p.add_argument("--width", type=int, default=None, help="terminal width for stone layout")
    p.add_argument(
        "--include-risen",
        action="store_true",
        help="also show files that were deleted and later re-added",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="walk every ref's first-parent chain, interleaved by date; a file deleted "
        "on one branch but alive on another is reported dead, and ages can be off",
    )
    p.add_argument(
        "--no-lines",
        action="store_true",
        help="skip line counts entirely (they are the slow part on big repos)",
    )
    p.add_argument("--version", action="version", version=f"git-epitaph {__version__}")
    return p


def _parse_since(value: str) -> int:
    try:
        return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"wants YYYY-MM-DD, got {value!r}") from exc


def _non_negative(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def _repo_root(repo: Path) -> Path:
    """Resolve `repo` (a work tree, any subdirectory of one, or a bare repo) to its root.

    Everything after this runs from the root: `ls-tree` limits itself to the cwd and
    `diff-tree` pathspecs are cwd-relative, so a subdirectory argument would otherwise
    lose living paths and miss every lazy line count.
    """
    try:
        out, _ = run_git(repo, "rev-parse", "--is-inside-work-tree", "--is-bare-repository")
    except GitError as exc:
        if "not found on PATH" in str(exc):
            raise
        raise GitError(f"not a git repository: {repo}") from exc
    in_work_tree, is_bare = out.split()
    if is_bare == "true":
        root, _ = run_git(repo, "rev-parse", "--absolute-git-dir")
    elif in_work_tree == "true":
        root, _ = run_git(repo, "rev-parse", "--show-toplevel")
    else:
        raise GitError(f"not a git repository: {repo}")
    return Path(root.strip())


# above this --limit, one numstat pass in the log is cheaper than a diff-tree per death
# commit. it keys off the limit, not the shown count, because the choice has to be made
# before the walk; a tight --path filter with a huge limit pays for the full pass.
LAZY_LIMIT = 200


def fill_lines(repo: Path, graves: list[Grave]) -> None:
    """Count lines for just these graves, one diff-tree per death commit."""
    by_commit: dict[str, list[Grave]] = {}
    for g in graves:
        by_commit.setdefault(g.died_sha, []).append(g)
    for sha, group in by_commit.items():
        counts = deleted_lines_in(repo, sha, [g.path for g in group])
        for g in group:
            if g.path not in counts:
                # both commands run from the repo root against the same first parent, so a
                # D in the log is a D here. a miss means they disagree; guessing would hide it.
                raise GitError(f"could not count lines for {g.path!r} in {sha[:12]}")
            g.set_lines(counts[g.path])


def select(graves: list[Grave], args: argparse.Namespace) -> list[Grave]:
    out = graves
    if not args.include_risen:
        out = [g for g in out if not g.risen]
    if args.since is not None:
        out = [g for g in out if g.died >= args.since]
    if args.path:
        pat = args.path
        out = [
            g
            for g in out
            if fnmatch.fnmatch(g.path, pat)
            or fnmatch.fnmatch(g.born_path, pat)
            or any(fnmatch.fnmatch(a, pat) for a in g.aliases)
        ]
    out = sorted(out, key=SORT_KEYS[args.sort], reverse=True)
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # counting lines reads every deleted blob and is ~95% of the wall time on big repos.
    # only pay for all of it when the answer needs all of it.
    count_all = not args.no_lines and (
        args.limit is None or args.sort == "lines" or args.limit > LAZY_LIMIT
    )
    try:
        repo = _repo_root(Path(args.repo))
        commits, warnings = read_log(repo, all_refs=args.all, count_lines=count_all)
        living = living_paths(repo, all_refs=args.all)
    except GitError as exc:
        print(f"git-epitaph: {exc}", file=sys.stderr)
        return 2
    if warnings:
        # e.g. "inexact rename detection was skipped": renames in that commit will show
        # as a death plus a birth, and the user deserves to know why.
        print(f"git-epitaph: git says: {warnings}", file=sys.stderr)

    all_graves = bury(commits, living=living)
    graves = select(all_graves, args)
    shown = graves[: args.limit] if args.limit is not None else graves

    if not count_all and not args.no_lines:
        try:
            fill_lines(repo, shown)
        except GitError as exc:
            print(f"git-epitaph: {exc}", file=sys.stderr)
            return 2

    if args.json:
        print(to_json(shown))
        return 0

    if not graves:
        if all_graves:
            print(f"nothing buried matches those filters ({len(all_graves)} graves in total).")
        else:
            print("nothing buried here. every file ever committed is still alive.")
        return 0

    style = args.style
    if style == "auto":
        style = "stones" if sys.stdout.isatty() else "list"
    width = args.width or shutil.get_terminal_size((80, 24)).columns

    # totals over everything, so "risen" is a real number even though risen graves are
    # hidden by default
    header = summary(all_graves)
    if len(shown) != len(all_graves):
        header += f" (showing {len(shown)})"
    print(header)
    print()
    print(render_stones(shown, width=width) if style == "stones" else render_list(shown))
    return 0
