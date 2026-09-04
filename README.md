# git-epitaph

every repo has a graveyard. `git log --diff-filter=D` will show you the bodies, one
commit at a time, with no birth dates, no line counts, and no way to tell a file that
was renamed from one that actually died. nobody reads it.

`git epitaph` walks the whole history once and prints a tombstone for every file that
was ever deleted: when it was born, when it died, how many lines it had, who deleted it,
and the commit message that did it. renames carry the birth date forward instead of
counting as a death. files that came back later get marked as risen.

```
$ git epitaph -n 3
123 buried, 0 risen, 80123 lines lost (showing 3)

   .---------------------.        .---------------------.        .---------------------.
  /                       \      /                       \      /                       \
  |         R.I.P.        |      |         R.I.P.        |      |         R.I.P.        |
  |                       |      |                       |      |                       |
  | …rop-99eb07/README.md |      | …joe-writing-voice.md |      | …99eb07/kaomojidex.md |
  |        9 lines        |      |        73 lines       |      |       633 lines       |
  |                       |      |                       |      |                       |
  |       2026-08-24      |      |       2026-08-24      |      |       2026-08-24      |
  |       2026-08-24      |      |       2026-08-24      |      |       2026-08-24      |
  |                       |      |                       |      |                       |
  |  swept up in a chore  |      |  swept up in a chore  |      |  swept up in a chore  |
  |                       |      |                       |      |                       |
 _|_______________________|_    _|_______________________|_    _|_______________________|_
```

(that repo is [PromptPressure](https://github.com/StressTestor/PromptPressure). 146 commits,
about 0.3s of CPU.)

stdlib only. no network, no API keys, no hooks to install, nothing written into your repo.
it reads `git log` and that's the whole trick.

## install

```
uv tool install git-epitaph
# or
pipx install git-epitaph
```

that puts `git-epitaph` on your PATH, which means `git epitaph` works as a subcommand.
python 3.10+, git 2.x.

## usage

```
git epitaph                      # stones in a terminal, plain list when piped
git epitaph -n 10 --sort lines   # the ten biggest things you ever deleted
git epitaph --sort age           # longest-lived files that eventually died
git epitaph --since 2026-01-01   # deaths this year
git epitaph --path 'src/**'      # only one subtree (matches old names too)
git epitaph --include-risen      # show files that were deleted and later re-added
git epitaph --all                # walk every ref, not just HEAD
git epitaph --json | jq          # machine readable
git epitaph --style list         # one block per grave with a resurrection command
```

the list style includes the exact command to bring a file back:

```
$ git epitaph -n 1 --sort lines --style list
123 buried, 0 risen, 80123 lines lost (showing 1)

desktop/build/sidecar/xref-sidecar.html
  2026-01-30 -> 2026-03-25  54 days  52869 lines  deliberately removed
  killed by StressTestor in 72ac23592725: delete desktop/ directory and update .gitignore
  git checkout 72ac23592725^ -- 'desktop/build/sidecar/xref-sidecar.html'
```

## cause of death

the cause is read off the deleting commit's subject. conventional commit types map
directly (`refactor:` is "refactored out of existence", `fix:` is "was the bug",
`revert:` is "reverted, never happened"). without a type prefix it looks for removal
words like remove, delete, drop, prune, purge, and falls back to "unknown causes".
a subject starting with `wip` is "died of wip". the full table is in `cause.py`.

## what counts as dead

a file is dead when a commit on the walked history deletes it and no later commit adds
it back at the same path. a rename (`R` in `git log -M`) keeps the birth record and adds
the old name to `aliases`. a copy (`C`) starts a fresh birth for the copy. a file that
existed before the available history (shallow clone) gets `????-??-??` for its birth.

merge commits are walked but their combined diff is skipped, same as plain `git log`,
so a deletion is attributed to the commit that actually made it.

## limitations

- one `git log --raw --numstat -M` over the full history. fine for tens of thousands of
  commits, slow on the linux kernel.
- rename detection is git's heuristic (`-M`, 50% similarity). a rewrite-and-rename will
  show as a death plus an unrelated birth, because that is what git says happened.
- line counts come from numstat, so binaries show as `binary` instead of a number.

## development

```
uv sync
uv run pytest
uv run ruff check .
```

## license

MIT
