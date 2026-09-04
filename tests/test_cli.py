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


def test_since_filter(repo: Path, capsys):
    assert main([str(repo), "--json", "--since", "2023-11-25"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [g["path"] for g in data] == ["img.png"]


def test_sort_by_lines(repo: Path, capsys):
    assert main([str(repo), "--json", "--sort", "lines"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["path"] == "legacy.py"


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
