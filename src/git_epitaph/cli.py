"""`git epitaph`: walk a repo's history and print a tombstone for every deleted file."""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from git_epitaph import __version__
from git_epitaph.gitlog import GitError, living_paths, read_log, run_git
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
        help="walk all refs as one timeline; a file deleted on one branch but alive on "
        "another is reported dead",
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


def _assert_repo(repo: Path) -> None:
    """Accept work trees and bare repos; reject everything else before doing any work."""
    try:
        out, _ = run_git(repo, "rev-parse", "--is-inside-work-tree", "--is-bare-repository")
    except GitError as exc:
        if "not found on PATH" in str(exc):
            raise
        raise GitError(f"not a git repository: {repo}") from exc
    if "true" not in out.split():
        raise GitError(f"not a git repository: {repo}")


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
    repo = Path(args.repo)
    try:
        _assert_repo(repo)
        commits, warnings = read_log(repo, all_refs=args.all)
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
