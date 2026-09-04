# git-epitaph

every repo has a graveyard. `git log --diff-filter=D` will show you the bodies, one
commit at a time, without birth dates or line counts, and it can't tell a rename from a
real death. nobody reads it.

`git epitaph` walks the mainline once and prints a tombstone for every file that was ever
deleted: when it was born, when it died, how many lines it had, who deleted it, and the
commit message that did it. renames carry the birth date forward instead of counting as a
death. files that came back later get marked as risen.

```
$ git epitaph -n 3
124 buried, 1 risen (showing 3)

   .---------------------.        .---------------------.        .---------------------.
  /                       \      /                       \      /                       \
  |        R.I.P.         |      |        R.I.P.         |      |        R.I.P.         |
  |                       |      |                       |      |                       |
  | …rop-99eb07/README.md |      | …joe-writing-voice.md |      | …99eb07/kaomojidex.md |
  |        9 lines        |      |       73 lines        |      |       633 lines       |
  |                       |      |                       |      |                       |
  |      2026-08-24       |      |      2026-08-24       |      |      2026-08-24       |
  |      2026-08-24       |      |      2026-08-24       |      |      2026-08-24       |
  |                       |      |                       |      |                       |
  |  swept up in a chore  |      |  swept up in a chore  |      |  swept up in a chore  |
  |                       |      |                       |      |                       |
 _|_______________________|_    _|_______________________|_    _|_______________________|_
```

(that repo is [PromptPressure](https://github.com/StressTestor/PromptPressure), 146 commits.)

stdlib only, and the only thing it runs is `git`. nothing gets written into your repo and
nothing leaves your machine.

## install

```
uv tool install git-epitaph
# or
pipx install git-epitaph
```

that puts `git-epitaph` on your PATH, which means `git epitaph` works as a subcommand.
python 3.10+, git 2.31+.

## usage

```
git epitaph                      # stones in a terminal, plain list when piped
git epitaph -n 10 --sort lines   # the ten biggest things you ever deleted
git epitaph --sort age           # longest-lived files that eventually died
git epitaph --since 2026-01-01   # deaths this year
git epitaph --path 'src/**'      # only one subtree (matches old names too)
git epitaph --include-risen      # show files that were deleted and later re-added
git epitaph --no-lines           # skip line counts, the slow part on big repos
git epitaph --all                # walk every ref, not just HEAD
git epitaph --json | jq          # machine readable
git epitaph --style list         # one block per grave with a resurrection command
```

the list style includes the exact command to bring a file back:

```
$ git epitaph -n 1 --sort lines --style list
124 buried, 1 risen, 80455 lines lost (showing 1)

desktop/build/sidecar/xref-sidecar.html
  2026-01-30 -> 2026-03-25  54 days  52869 lines  deliberately removed
  killed by StressTestor in 72ac23592725: delete desktop/ directory and update .gitignore
  git checkout 72ac23592725^ -- 'desktop/build/sidecar/xref-sidecar.html'
```

## cause of death

the cause is read off the deleting commit's subject. conventional commit types map
directly (`refactor:` is "refactored out of existence", `fix:` is "was the bug",
`revert:` and git's own `Revert "..."` are "reverted, never happened"). without a type
prefix it looks for removal words like remove, delete, drop, prune, purge, and falls back
to "unknown causes". a subject starting with `wip` is "died of wip". the full table is in
`src/git_epitaph/cause.py`.

## what counts as dead

the walk is `git log --first-parent`, with each merge diffed against its first parent.
that's the mainline: a straight line where every merged PR lands as one net change at the
merge commit. a file is dead when a mainline commit deletes it and no later one adds it
back at the same path.

the straight line is what makes the numbers trustworthy. walking every commit instead
interleaves branches, and on [hermes-agent](https://github.com/NousResearch/hermes-agent)
that produced 11 graves with negative ages (a path added on one branch, an unrelated file
of the same name deleted on another) and 5 files with no birth at all (created inside a
merge conflict resolution, which plain `git log` never shows). on the mainline both
numbers are zero.

it also means a file that lived and died inside a PR branch without ever reaching main
isn't in the graveyard.

a rename (`R` in `git log -M`) keeps the birth record and adds the old name to `aliases`.
copies aren't detected; a copied file is just a new file. a file that existed before the
available history (shallow clone) gets `????-??-??` for its birth. dates are committer
times, so rebases and cherry-picks don't produce negative ages.

## speed

line counts are the expensive part: git has to read every deleted blob to count them.
so with `-n` and a sort other than `lines`, the big walk skips them and only the shown
graves get counted afterwards.

| repo | commits | `-n 6` | full count |
|---|---|---|---|
| PromptPressure | 146 | 0.3s | 0.3s |
| hermes-agent | 27,617 | 16s | 45s |
| openclaw | 87,468 | 77s | 4.5 min |

measured on a bare clone on a USB SSD. `--no-lines` gets you the `-n 6` time without a
limit.

## limitations

- rename detection is git's heuristic (`-M`, 50% similarity). a rewrite-and-rename shows
  as a death plus an unrelated birth, because that's what git says happened.
- binaries show as `binary` instead of a line count.
- `--all` flattens every ref into one timeline. a file deleted on a feature branch but
  alive on main is reported dead. HEAD only (the default) has no such ambiguity.
- control characters in paths, authors and commit subjects are escaped on output, so a
  hostile clone can't drive your terminal through a commit message.

## development

```
uv sync
uv run pytest
uv run ruff check .
```

## license

MIT
