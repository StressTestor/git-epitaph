import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from git_epitaph.cli import main

DAY = 86400
T0 = 1_700_000_000


def git(repo: Path, *args: str, ts: int | None = None) -> str:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "joe",
            "GIT_AUTHOR_EMAIL": "joe@example.invalid",
            "GIT_COMMITTER_NAME": "joe",
            "GIT_COMMITTER_EMAIL": "joe@example.invalid",
        }
    )
    if ts is not None:
        env["GIT_AUTHOR_DATE"] = f"{ts} +0000"
        env["GIT_COMMITTER_DATE"] = f"{ts} +0000"
    proc = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} exited {proc.returncode}:\n{proc.stderr}")
    return proc.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "keep.py").write_text("print('alive')\n")
    (r / "old.py").write_text("\n".join(f"line {i}" for i in range(20)) + "\n")
    (r / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    git(r, "add", "keep.py", "old.py", "img.png")
    git(r, "commit", "-q", "-m", "feat: initial", ts=T0)

    git(r, "mv", "old.py", "legacy.py")
    git(r, "commit", "-q", "-m", "refactor: rename old to legacy", ts=T0 + DAY)

    git(r, "rm", "-q", "legacy.py")
    git(r, "commit", "-q", "-m", "refactor(core): drop legacy module", ts=T0 + 10 * DAY)

    git(r, "rm", "-q", "img.png")
    git(r, "commit", "-q", "-m", "chore: remove image", ts=T0 + 12 * DAY)

    # resurrect and re-kill img.png to exercise the risen path
    (r / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n\x01")
    git(r, "add", "img.png")
    git(r, "commit", "-q", "-m", "revert: bring image back", ts=T0 + 13 * DAY)
    git(r, "rm", "-q", "img.png")
    git(r, "commit", "-q", "-m", "chore: remove image again", ts=T0 + 14 * DAY)
    return r


def test_json_output_end_to_end(repo: Path, capsys):
    assert main([str(repo), "--json", "--include-risen"]) == 0
    data = json.loads(capsys.readouterr().out)
    paths = sorted(g["path"] for g in data)
    assert paths == ["img.png", "img.png", "legacy.py"]
    legacy = next(g for g in data if g["path"] == "legacy.py")
    assert legacy["born_path"] == "old.py"
    assert legacy["aliases"] == ["old.py"]
    assert legacy["lines"] == 20
    assert legacy["age_days"] == 10
    assert legacy["cause"] == "refactored out of existence"
    assert legacy["killer"] == "joe"
    risen = [g for g in data if g["path"] == "img.png" and g["risen"]]
    assert len(risen) == 1


def test_default_excludes_risen(repo: Path, capsys):
    assert main([str(repo), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert all(not g["risen"] for g in data)
    assert len(data) == 2


def test_list_style_and_filters(repo: Path, capsys):
    assert main([str(repo), "--style", "list", "--path", "*.py"]) == 0
    out = capsys.readouterr().out
    assert "legacy.py" in out
    assert "img.png" not in out
    assert "git checkout" in out


def test_stones_default_and_limit(repo: Path, capsys):
    assert main([str(repo), "--style", "stones", "--limit", "1", "--width", "60"]) == 0
    out = capsys.readouterr().out
    assert "R.I.P." in out
    # newest death first by default: img.png (second death) is the only stone
    assert "img.png" in out
    assert "legacy.py" not in out


@pytest.fixture
def git_spy(monkeypatch):
    """Records the count_lines flag of every read_log call and the paths of every
    deleted_lines_in call, without changing what they do."""
    import git_epitaph.cli as cli

    calls = {"count_lines": [], "diff_tree_paths": []}
    real_log, real_lines = cli.read_log, cli.deleted_lines_in

    def log_spy(repo_, all_refs=False, count_lines=True):
        calls["count_lines"].append(count_lines)
        return real_log(repo_, all_refs=all_refs, count_lines=count_lines)

    def lines_spy(repo_, sha, paths):
        calls["diff_tree_paths"].append(list(paths))
        return real_lines(repo_, sha, paths)

    monkeypatch.setattr(cli, "read_log", log_spy)
    monkeypatch.setattr(cli, "deleted_lines_in", lines_spy)
    return calls


def test_limit_counts_only_the_shown_graves(repo: Path, capsys, git_spy):
    assert main([str(repo), "--json", "--limit", "1", "--sort", "age"]) == 0
    assert git_spy["count_lines"] == [False]  # the big walk skipped numstat
    assert git_spy["diff_tree_paths"] == [["legacy.py"]]  # and only the shown grave got counted
    (g,) = json.loads(capsys.readouterr().out)
    assert g["path"] == "legacy.py"
    assert g["lines"] == 20 and g["lines_counted"] is True and g["binary"] is False


def test_lazy_count_reports_binaries_as_binary(repo: Path, capsys, git_spy):
    # longest-lived grave including risen ones is the first img.png (12 days), whose
    # fixture bytes contain a NUL, so git calls it binary
    assert main([str(repo), "--json", "-n", "1", "--sort", "age", "--include-risen"]) == 0
    assert git_spy["count_lines"] == [False]
    assert git_spy["diff_tree_paths"] == [["img.png"]]
    (img,) = json.loads(capsys.readouterr().out)
    assert img["path"] == "img.png" and img["risen"] is True
    assert img["lines"] is None and img["binary"] is True and img["lines_counted"] is True


def test_subdirectory_argument_behaves_like_the_root(repo: Path, capsys):
    sub = repo / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("x = 1\ny = 2\n")
    (sub / "__init__.py").write_text("")  # keeps the directory alive after the rm
    git(repo, "add", "pkg")
    git(repo, "commit", "-q", "-m", "feat: pkg", ts=T0 + 20 * DAY)
    git(repo, "rm", "-q", "pkg/mod.py")
    git(repo, "commit", "-q", "-m", "chore: drop pkg", ts=T0 + 21 * DAY)

    assert main([str(repo), "--json", "-n", "3", "--include-risen"]) == 0
    from_root = json.loads(capsys.readouterr().out)
    assert main([str(sub), "--json", "-n", "3", "--include-risen"]) == 0
    from_sub = json.loads(capsys.readouterr().out)
    assert from_sub == from_root
    assert from_root[0]["path"] == "pkg/mod.py" and from_root[0]["lines"] == 2


def test_sort_by_lines_forces_a_full_count(repo: Path, capsys, git_spy):
    assert main([str(repo), "--json", "--limit", "1", "--sort", "lines"]) == 0
    assert git_spy["count_lines"] == [True]
    assert git_spy["diff_tree_paths"] == []
    assert json.loads(capsys.readouterr().out)[0]["path"] == "legacy.py"


def test_huge_limit_prefers_one_numstat_pass(repo: Path, capsys, git_spy):
    from git_epitaph.cli import LAZY_LIMIT

    assert main([str(repo), "--json", "--limit", str(LAZY_LIMIT + 1)]) == 0
    assert git_spy["count_lines"] == [True]
    assert git_spy["diff_tree_paths"] == []


def test_limit_header_drops_lines_lost_because_they_were_not_counted(repo: Path, capsys):
    assert main([str(repo), "--style", "list", "--include-risen"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "3 buried, 1 risen, 23 lines lost"
    assert main([str(repo), "--style", "list", "--include-risen", "-n", "1"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "3 buried, 1 risen (showing 1)"


def test_lazy_count_takes_paths_literally(repo: Path, capsys):
    # `:` is pathspec magic (matches nothing) and `[slug]` is a one-character glob that
    # does not match the literal file named `[slug].tsx`; both must be plain bytes
    for name in (":colon.txt", "[slug].tsx"):
        (repo / name).write_text("one\ntwo\n")
    git(repo, "--literal-pathspecs", "add", "--", ":colon.txt", "[slug].tsx")
    git(repo, "commit", "-q", "-m", "feat: odd names", ts=T0 + 20 * DAY)
    git(repo, "--literal-pathspecs", "rm", "-q", "--", ":colon.txt", "[slug].tsx")
    git(repo, "commit", "-q", "-m", "chore: drop odd names", ts=T0 + 21 * DAY)
    assert main([str(repo), "--json", "-n", "2"]) == 0
    data = {g["path"]: g for g in json.loads(capsys.readouterr().out)}
    assert set(data) == {":colon.txt", "[slug].tsx"}
    assert all(g["lines"] == 2 and g["lines_counted"] for g in data.values())


def test_lazy_count_miss_is_an_error_not_a_shrug(repo: Path, capsys, monkeypatch):
    import git_epitaph.cli as cli

    monkeypatch.setattr(cli, "deleted_lines_in", lambda repo_, sha, paths: {})
    assert main([str(repo), "--json", "-n", "1"]) == 2
    err = capsys.readouterr().err
    assert "could not count lines" in err and "img.png" in err


def test_no_lines_skips_counting_and_says_so(repo: Path, capsys):
    assert main([str(repo), "--no-lines", "--style", "list"]) == 0
    out = capsys.readouterr().out
    assert "lines lost" not in out.splitlines()[0]
    assert "lines not counted" in out
    assert main([str(repo), "--no-lines", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert all(g["lines"] is None and g["lines_counted"] is False for g in data)


def test_since_filter(repo: Path, capsys):
    assert main([str(repo), "--json", "--since", "2023-11-25"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [g["path"] for g in data] == ["img.png"]


def test_sort_by_lines(repo: Path, capsys):
    assert main([str(repo), "--json", "--sort", "lines"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["path"] == "legacy.py"


def test_header_counts_risen_even_though_they_are_hidden(repo: Path, capsys):
    assert main([str(repo), "--style", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("3 buried, 1 risen")
    assert "(showing 2)" in out


def _conflicting_merge(repo: Path, extra_file: str | None = None) -> str:
    """Branch deletes keep.py, main edits it, merge keeps it. Returns the merge sha."""
    git(repo, "checkout", "-q", "-b", "purge")
    git(repo, "rm", "-q", "keep.py")
    git(repo, "commit", "-q", "-m", "chore: drop keep.py on a branch", ts=T0 + 30 * DAY)
    git(repo, "checkout", "-q", "main")
    (repo / "keep.py").write_text("print('still here')\n")
    git(repo, "add", "keep.py")
    git(repo, "commit", "-q", "-m", "fix: touch keep.py", ts=T0 + 31 * DAY)
    merge = subprocess.run(["git", "merge", "purge"], cwd=repo, capture_output=True, text=True)
    assert merge.returncode == 1 and "CONFLICT (modify/delete)" in merge.stdout, (
        merge.stdout + merge.stderr
    )
    git(repo, "add", "keep.py")
    if extra_file:
        (repo / extra_file).write_text("born in a merge\n")
        git(repo, "add", extra_file)
    git(repo, "-c", "core.editor=true", "commit", "-q", "--no-edit", ts=T0 + 32 * DAY)
    assert (repo / "keep.py").exists()
    return git(repo, "rev-parse", "HEAD").strip()


def test_file_deleted_on_branch_but_kept_by_merge_never_died_on_mainline(repo: Path, capsys):
    _conflicting_merge(repo)
    assert main([str(repo), "--json", "--include-risen"]) == 0
    paths = [g["path"] for g in json.loads(capsys.readouterr().out)]
    assert "keep.py" not in paths


def test_file_born_inside_a_merge_resolution_has_a_known_birth(repo: Path, capsys):
    merge_sha = _conflicting_merge(repo, extra_file="newborn.py")
    git(repo, "rm", "-q", "newborn.py")
    git(repo, "commit", "-q", "-m", "chore: remove newborn", ts=T0 + 40 * DAY)
    assert main([str(repo), "--json", "--path", "newborn.py"]) == 0
    (g,) = json.loads(capsys.readouterr().out)
    assert g["born_sha"] == merge_sha
    assert g["age_days"] == 8


def test_branch_deletion_is_attributed_to_the_merge_that_landed_it(repo: Path, capsys):
    git(repo, "checkout", "-q", "-b", "cleanup")
    git(repo, "rm", "-q", "keep.py")
    git(repo, "commit", "-q", "-m", "chore: drop keep.py", ts=T0 + 50 * DAY)
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge PR #7: cleanup", "cleanup", ts=T0 + 51 * DAY)
    merge_sha = git(repo, "rev-parse", "HEAD").strip()
    assert main([str(repo), "--json", "--path", "keep.py"]) == 0
    (g,) = json.loads(capsys.readouterr().out)
    assert g["died_sha"] == merge_sha
    assert g["epitaph"] == "Merge PR #7: cleanup"
    assert g["age_days"] == 51
    assert g["lines"] == 1


def test_branch_and_mainline_deleting_the_same_file_do_not_cross(repo: Path, capsys):
    # the shape behind hermes-agent's bad graves: a PR deletes keep.py on its branch, main
    # lands the same deletion itself and then reverts it, the PR merges main into itself
    # and is merged. walking every commit, the PR's D pops the birth first, main's own D
    # gets an unknown birth, and the revert marks keep.py risen even though the final
    # merge kills it. on the mainline it is two clean graves.
    git(repo, "checkout", "-q", "-b", "pr")
    git(repo, "rm", "-q", "keep.py")
    git(repo, "commit", "-q", "-m", "feat: remove keep", ts=T0 + 20 * DAY)
    git(repo, "checkout", "-q", "main")
    git(repo, "rm", "-q", "keep.py")
    git(repo, "commit", "-q", "-m", "feat: remove keep (#1)", ts=T0 + 21 * DAY)
    git(repo, "revert", "--no-edit", "HEAD", ts=T0 + 22 * DAY)
    git(repo, "checkout", "-q", "pr")
    git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge branch 'main' into pr",
        "main",
        ts=T0 + 23 * DAY,
    )
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge PR #2", "pr", ts=T0 + 24 * DAY)
    assert not (repo / "keep.py").exists()

    assert main([str(repo), "--json", "--include-risen", "--path", "keep.py"]) == 0
    graves = sorted(json.loads(capsys.readouterr().out), key=lambda g: g["died"])
    assert [g["born"] is not None for g in graves] == [True, True]
    assert [g["age_days"] for g in graves] == [21, 2]
    assert [g["risen"] for g in graves] == [True, False]
    assert graves[1]["epitaph"] == "Merge PR #2"


def test_auto_style_picks_stones_on_a_tty_and_list_otherwise(repo: Path, capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert main([str(repo), "--width", "60"]) == 0
    assert "R.I.P." in capsys.readouterr().out
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "R.I.P." not in out
    assert "git checkout" in out


def test_git_warnings_are_surfaced_on_stderr(repo: Path, capsys, monkeypatch):
    import git_epitaph.cli as cli

    real = cli.read_log

    def noisy(*a, **k):
        commits, _ = real(*a, **k)
        return commits, "warning: inexact rename detection was skipped due to too many files."

    monkeypatch.setattr(cli, "read_log", noisy)
    assert main([str(repo), "--json"]) == 0
    assert "inexact rename detection" in capsys.readouterr().err


def test_missing_git_binary_exits_2(repo: Path, capsys, monkeypatch):
    import git_epitaph.gitlog as gitlog

    def no_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gitlog.subprocess, "run", no_git)
    assert main([str(repo)]) == 2
    assert "git not found on PATH" in capsys.readouterr().err


def test_bad_since_rejected_before_walking(repo: Path, capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("log walked despite bad --since")

    monkeypatch.setattr("git_epitaph.cli.read_log", boom)
    with pytest.raises(SystemExit) as exc:
        main([str(repo), "--since", "yesterday"])
    assert exc.value.code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_negative_limit_rejected(repo: Path, capsys):
    with pytest.raises(SystemExit) as exc:
        main([str(repo), "--limit", "-1"])
    assert exc.value.code == 2
    assert ">= 0" in capsys.readouterr().err


def test_filters_that_match_nothing_say_so(repo: Path, capsys):
    assert main([str(repo), "--path", "nope/*"]) == 0
    out = capsys.readouterr().out
    assert "matches those filters" in out
    assert "still alive" not in out


def test_bare_repo_is_accepted(repo: Path, tmp_path: Path, capsys):
    bare = tmp_path / "bare.git"
    git(repo, "clone", "-q", "--bare", str(repo), str(bare))
    assert main([str(bare), "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2


def test_non_ascii_subject_survives_latin1_locale(repo: Path):
    # LANG=C is coerced to UTF-8 by python itself (PEP 538), so a latin-1 locale is the
    # one that actually decodes git's UTF-8 output wrongly without an explicit encoding.
    (repo / "café.py").write_text("x\n")
    git(repo, "add", "café.py")
    git(repo, "commit", "-q", "-m", "feat: añadir café — ünïcode", ts=T0 + 20 * DAY)
    git(repo, "rm", "-q", "café.py")
    git(repo, "commit", "-q", "-m", "chore: quitar café — ünïcode", ts=T0 + 21 * DAY)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG"))}
    env.update(
        {
            "LANG": "en_US.ISO8859-1",
            "LC_ALL": "en_US.ISO8859-1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-m", "git_epitaph", str(repo), "--style", "list", "-n", "1"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "chore: quitar café — ünïcode" in proc.stdout
    assert "café.py" in proc.stdout


def test_not_a_repo_fails_loudly(tmp_path: Path, capsys):
    rc = main([str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not a git repository" in err


def test_empty_graveyard_message(tmp_path: Path, capsys):
    r = tmp_path / "fresh"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a").write_text("x")
    git(r, "add", "a")
    git(r, "commit", "-q", "-m", "init", ts=T0)
    assert main([str(r)]) == 0
    assert "nothing buried" in capsys.readouterr().out


def test_module_is_runnable(repo: Path):
    out = subprocess.run(
        [sys.executable, "-m", "git_epitaph", str(repo), "--json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert json.loads(out)
