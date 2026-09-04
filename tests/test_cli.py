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
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout


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


def test_limit_counts_lines_lazily_but_correctly(repo: Path, capsys, monkeypatch):
    import git_epitaph.cli as cli

    seen: list[bool] = []
    real = cli.read_log

    def spy(repo_, all_refs=False, count_lines=True):
        seen.append(count_lines)
        return real(repo_, all_refs=all_refs, count_lines=count_lines)

    monkeypatch.setattr(cli, "read_log", spy)
    assert main([str(repo), "--json", "--limit", "5", "--include-risen"]) == 0
    assert seen == [False]  # the big walk skipped numstat
    data = json.loads(capsys.readouterr().out)
    legacy = next(g for g in data if g["path"] == "legacy.py")
    assert legacy["lines"] == 20 and legacy["lines_counted"] is True
    # the first img.png (the risen one) has a NUL byte, so git calls it binary
    img = next(g for g in data if g["path"] == "img.png" and g["risen"])
    assert img["lines"] is None and img["binary"] is True and img["lines_counted"] is True


def test_sort_by_lines_forces_a_full_count(repo: Path, capsys, monkeypatch):
    import git_epitaph.cli as cli

    seen: list[bool] = []
    real = cli.read_log

    def spy(repo_, all_refs=False, count_lines=True):
        seen.append(count_lines)
        return real(repo_, all_refs=all_refs, count_lines=count_lines)

    monkeypatch.setattr(cli, "read_log", spy)
    assert main([str(repo), "--json", "--limit", "1", "--sort", "lines"]) == 0
    assert seen == [True]
    assert json.loads(capsys.readouterr().out)[0]["path"] == "legacy.py"


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
    subprocess.run(["git", "merge", "purge"], cwd=repo, capture_output=True)  # modify/delete
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


def test_same_path_added_on_two_branches_cannot_cross(repo: Path, capsys):
    # the interleaving that produced negative ages on hermes-agent: a path added on a
    # side branch with a later clock than the mainline deletion of an unrelated file of
    # the same name. first-parent makes the walk linear, so age is always >= 0.
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "dup.txt").write_text("side\n")
    git(repo, "add", "dup.txt")
    git(repo, "commit", "-q", "-m", "feat: side dup", ts=T0 + 90 * DAY)
    git(repo, "checkout", "-q", "main")
    (repo / "dup.txt").write_text("main\n")
    git(repo, "add", "dup.txt")
    git(repo, "commit", "-q", "-m", "feat: main dup", ts=T0 + 60 * DAY)
    git(repo, "rm", "-q", "dup.txt")
    git(repo, "commit", "-q", "-m", "chore: rm main dup", ts=T0 + 61 * DAY)
    subprocess.run(
        ["git", "merge", "--no-ff", "-m", "merge side", "side"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_COMMITTER_DATE": f"{T0 + 62 * DAY} +0000",
            "GIT_AUTHOR_DATE": f"{T0 + 62 * DAY} +0000",
        },
    )
    assert main([str(repo), "--json", "--include-risen", "--path", "dup.txt"]) == 0
    graves = json.loads(capsys.readouterr().out)
    assert all(g["age_days"] is not None and g["age_days"] >= 0 for g in graves)
    (g,) = graves
    assert g["age_days"] == 1
    assert g["risen"] is True  # the side branch's dup.txt arrived via the merge


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
