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
| git | 2.31+ | `--diff-merges=first-parent` |

## directory tree

```
git-epitaph/
  pyproject.toml            package metadata, script entry, ruff + pytest config
  README.md                 user docs (joe's voice)
  ARCHITECTURE.md           this file
  LICENSE                   MIT
  .github/workflows/
    ci.yml                  ruff + pytest matrix, SHA-pinned actions
    release.yml             tag -> build -> PyPI trusted publishing
  src/git_epitaph/
    __init__.py             __version__
    __main__.py             `python -m git_epitaph`
    gitlog.py               first-parent `git log --raw [--numstat] -M` -> Commit/Change;
                            `deleted_lines_in` for lazy per-commit counts
    walk.py                 replay commits, track births/renames/deaths -> Grave list
    cause.py                commit subject -> cause of death string
    render.py               stones / list / json renderers, summary line
    cli.py                  argparse, repo root resolution, lazy line counting, output
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

- **mainline walk.** `git log --reverse --first-parent --diff-merges=first-parent --raw
  [--numstat] -M`. first-parent makes history a straight line, so a birth is always an
  ancestor of its death and two branches adding the same path can never interleave.
  diffing each merge against its first parent makes a merged PR one net change at the
  merge commit, which also exposes files created or kept inside a conflict resolution.
  measured on hermes-agent: the every-commit walk gave 11 negative ages and 5 unknown
  births; the mainline walk gives 0 and 0.
- **two git calls, plus a few small ones.** the log pass gives per-path status
  (A/M/D/R) and, when requested, lines removed; `git ls-tree -r HEAD` gives the living
  set. `--name-status --numstat` does NOT combine (git prints only one), which is why
  `--raw` is used.
- **lazy line counts.** `--numstat` is ~95% of wall time on big repos (it reads every
  deleted blob; hermes-agent 25.7s with vs 1.1s without). `cli.main` only asks the log
  pass for counts when the answer needs all of them (no `--limit`, or `--sort lines`).
  otherwise `cli.fill_lines` runs one `git diff-tree --numstat sha^1 sha -- paths` per
  death commit for just the shown graves. `--no-lines` skips counting entirely.
  `Grave.counted` / `Grave.binary` keep "not counted" distinct from "binary".
- **living set is a consistency check.** on a first-parent walk the HEAD tree should
  never contain a buried path; if it does, `bury()` flips that grave to `risen` rather
  than lie.
- **committer time, not author time.** `%ct` is monotonic along a first-parent chain in
  practice; `%at` is whatever the contributor's clock said and yields negative ages.
- **custom record separators.** log format is `\x1e%H\x1f%at\x1f%an\x1f%s`. `\x1e` starts
  a commit, `\x1f` splits header fields, so subjects with newlines, tabs or colons never
  break parsing.
- **oldest-first replay.** `--reverse` lets `walk.bury` keep a dict of living files. `A`
  starts a `Birth`, `R` moves the birth to the new path and records the alias (a rename of
  a never-seen file keeps `born=None` rather than inventing a date), `D` pops the birth
  and emits a `Grave`. any `A`, `R` or `C` landing on a path that already has a grave
  flips that grave's `risen` flag. `C` is handled for completeness but never emitted,
  since the log runs with `-M` and not `-C`.
- **cause is derived, never stored.** `cause.cause_of_death(subject)` is called at render
  time. tests pin the table.
- **fail loudly.** any git failure raises `GitError` with git's stderr; the CLI prints it
  and exits 2. `--since` with a bad date exits with a message. no empty catches.
- **path quoting.** git C-quotes unusual paths (`core.quotePath`). `gitlog.unquote`
  reverses it, including octal UTF-8 escapes. output for shell use is single-quoted with
  `'\''` escaping, never `shlex.quote`, so paths are always visibly quoted.
- **repo content is untrusted.** everything that came from git (path, author, subject)
  passes through `render.clean()` before printing. non-printable characters, including
  the lone surrogates a non-UTF-8 filename decodes to, become escapes instead of crashing
  `print`. JSON strings go through `_json_safe()` so surrogates become the original byte
  as `\xNN`.
- **display cells, not code points.** stone text is centred with `render.cell_width()`
  (east asian wide/fullwidth = 2, combining = 0) so CJK paths keep the rectangle.
- **git warnings are not swallowed.** stderr from a successful `git log` (e.g. "inexact
  rename detection was skipped") is echoed to stderr, since it means renames in that
  commit were reported as death plus birth.
- **validate before work.** `--since` and `--limit` are argparse `type=` converters, so a
  bad value exits 2 before the (possibly slow) log walk starts.

## database schema

none. nothing is persisted.

## environment variables

none read by the tool. tests set `GIT_AUTHOR_*` / `GIT_COMMITTER_*` to get deterministic
timestamps and authors.

## deployment / ci

- `.github/workflows/ci.yml`: ruff check, ruff format --check, pytest on ubuntu + macos,
  python 3.10 and 3.13, `uv sync --frozen` against the lockfile.
- `.github/workflows/release.yml`: on a `v*` tag, run tests, assert the tag matches
  `uv version`, `uv build`, then publish to PyPI through trusted publishing (OIDC, github
  environment `pypi`, no token stored anywhere). the pypi side needs a pending publisher
  for owner `StressTestor`, repo `git-epitaph`, workflow `release.yml`, environment `pypi`.
- every action is pinned to a full commit SHA with the version in a trailing comment.
  bump by re-resolving the tag: `gh api repos/OWNER/REPO/git/ref/tags/TAG`.

release: bump `version` in `pyproject.toml`, commit, `git tag vX.Y.Z`, push the tag.

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
| non-ASCII subjects come out as `cafÃ©` under a latin-1 locale | `subprocess.run(text=True)` decodes with the locale codec; git emits UTF-8 | `encoding="utf-8"` on the git call; test pinned with `LANG=en_US.ISO8859-1` (`LANG=C` is coerced to UTF-8 by python and does not reproduce) |
| commit subject with `\x1b[...` drives the terminal | output printed raw | `render.clean()` escapes every non-printable char in path/author/subject |
| bad `--since` only errored after the full log walk | validation lived in `select()` | `--since` and `--limit` are argparse `type=` callbacks, so argparse exits 2 before git runs |
| "every file is still alive" printed when filters matched nothing | one empty-check for two situations | separate message when `all_graves` is non-empty |
| bare repo reported as "not a git repository" | only `--is-inside-work-tree` was checked | also accept `--is-bare-repository` |
| file deleted on a branch, kept by merge resolution, reported dead | `git log` shows no diff for merges | `--first-parent --diff-merges=first-parent`: the merge's net diff is what's walked, so the branch `D` never appears |
| 11 negative ages and 5 unknown births on hermes-agent | every-commit walk interleaves branches; merge-born files have no `A` row | same fix: mainline walk. `tests/test_cli.py::test_same_path_added_on_two_branches_cannot_cross` |
| 4.5 min on openclaw (87k commits) | `--numstat` reads every deleted blob | lazy counting when `--limit` is set (77s), `--no-lines` to skip |
| README claimed copies (`C`) start a fresh birth | log runs with `-M` only; `C` needs `-C` | README corrected; code path kept as a no-op guard |
| zsh loop `for f in "--raw -M"; git $f` gave 0.00s timings | zsh doesn't word-split unquoted `$f`, git got one bogus arg and exited | `${=f}` |
| header always said "0 risen" | summary ran on the already-filtered list | summary over `all_graves`, "(showing N)" for the filtered view |
| `Revert "..."` landed in "unknown causes" | only `revert:` (conventional) was matched | `_GIT_REVERT` regex for git's native subject shape |
| missing `git` binary gave a traceback | only `GitError` was caught | `run_git` turns `FileNotFoundError` into `GitError("git not found on PATH")` |
| `\udcff` in JSON instead of the real byte | `backslashreplace` straight from the surrogate | encode `surrogateescape` first, then decode `backslashreplace` |

## commands

```
uv sync                                   # create .venv with dev deps
uv run pytest                             # 82 tests
uv run ruff check . && uv run ruff format --check .
uv run git-epitaph <repo> -n 5            # try it
uv build                                  # sdist + wheel
```

last updated: 2026-09-03
