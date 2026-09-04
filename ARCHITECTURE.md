# architecture

## overview

`git-epitaph` is a single-purpose CLI. it runs one `git log` over a repository, replays
the history oldest-first, and produces a `Grave` record for every file deletion. three
renderers (ASCII stones, flat list, JSON) print the result. no state is written anywhere.

## stack

| layer | choice | why |
|---|---|---|
| language | python 3.10+ | stdlib only, ships anywhere git does |
| deps (runtime) | none | `subprocess`, `argparse`, `json`, `textwrap`, `fnmatch` |
| build | hatchling 1.27.0 (pinned) | src layout, console script entry point |
| dev | uv, pytest 8.4.1, ruff 0.12.7 (pinned in `pyproject.toml`) | |
| entry point | `git-epitaph` console script | lets git dispatch `git epitaph` |

## directory tree

```
git-epitaph/
  pyproject.toml            package metadata, script entry, ruff + pytest config
  README.md                 user docs (joe's voice)
  ARCHITECTURE.md           this file
  LICENSE                   MIT
  src/git_epitaph/
    __init__.py             __version__
    __main__.py             `python -m git_epitaph`
    gitlog.py               run `git log --raw --numstat -M`, parse into Commit/Change
    walk.py                 replay commits, track births/renames/deaths -> Grave list
    cause.py                commit subject -> cause of death string
    render.py               stones / list / json renderers, summary line
    cli.py                  argparse, filtering, sorting, style selection
  tests/
    test_gitlog.py          parser on captured log text (renames, binaries, quoted paths)
    test_walk.py            state machine: rename carries birth, risen, unknown birth, copy
    test_cause.py           cause table, removal keywords, wip, fallback
    test_render.py          stone geometry, list format, json fields, summary
    test_cli.py             end-to-end on a temp git repo built with fixed timestamps
```

## key patterns

data flow is a straight pipe:

```
git log ──▶ gitlog.parse_log ──▶ list[Commit] ──▶ walk.bury ──▶ list[Grave]
                                                                    │
                                                  cli.select (risen / since / path / sort)
                                                                    │
                                              render.{render_stones,render_list,to_json}
```

- **one git call.** `--raw` gives per-path status (A/M/D/R/C), `--numstat` gives lines
  removed. combining them in one invocation is what keeps the tool O(history) instead of
  O(files) subprocesses. `--name-status --numstat` does NOT combine (git prints only one),
  which is why `--raw` is used.
- **custom record separators.** log format is `\x1e%H\x1f%at\x1f%an\x1f%s`. `\x1e` starts
  a commit, `\x1f` splits header fields, so subjects with newlines, tabs or colons never
  break parsing.
- **oldest-first replay.** `--reverse` lets `walk.bury` keep a dict of living files. `A`
  starts a `Birth`, `R` moves the birth to the new path and records the alias, `C` starts
  a fresh birth for the copy, `D` pops the birth and emits a `Grave`. an `A` at a path that
  already has a grave flips that grave's `risen` flag.
- **cause is derived, never stored.** `cause.cause_of_death(subject)` is called at render
  time. tests pin the table.
- **fail loudly.** any git failure raises `GitError` with git's stderr; the CLI prints it
  and exits 2. `--since` with a bad date exits with a message. no empty catches.
- **path quoting.** git C-quotes unusual paths (`core.quotePath`). `gitlog.unquote`
  reverses it, including octal UTF-8 escapes. output for shell use is single-quoted with
  `'\''` escaping, never `shlex.quote`, so paths are always visibly quoted.

## database schema

none. nothing is persisted.

## environment variables

none read by the tool. tests set `GIT_AUTHOR_*` / `GIT_COMMITTER_*` to get deterministic
timestamps and authors.

## deployment / ci

no CI yet. release path is `uv build` then publish to PyPI as `git-epitaph`. no GitHub
Actions in the repo at time of writing, so nothing to pin.

## integrations

git only, via subprocess. requires `git` on PATH and a repo with history.

## gotchas

| problem | cause | fix |
|---|---|---|
| count differs from `git log --diff-filter=D --name-only \| sort -u` | default view hides files that were deleted and later re-added | `--include-risen` matches git's count |
| `--name-status --numstat` shows only one of the two | git picks the last diff format flag | use `--raw --numstat` |
| stone widths uneven in tests | `rstrip()` on joined rows trimmed the last column | rows are not stripped; trailing spaces are intentional |
| test wanted "refactored out of existence" on one line | cause wraps to two 21-char rows inside the stone | assert on the two fragments |
| a rewrite-and-rename shows as death + unrelated birth | git's `-M` similarity threshold (50%) did not link them | expected; that is what git reports |
| `hatchling` editable build fails with "Readme file does not exist" | `readme = "README.md"` in pyproject before the file existed | README must exist before `uv sync` |

## commands

```
uv sync                                   # create .venv with dev deps
uv run pytest                             # 52 tests
uv run ruff check . && uv run ruff format --check .
uv run git-epitaph <repo> -n 5            # try it
uv build                                  # sdist + wheel
```

last updated: 2026-09-03
