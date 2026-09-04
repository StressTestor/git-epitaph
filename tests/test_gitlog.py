import pytest

from git_epitaph.gitlog import Change, parse_log, unquote

RS = "\x1e"
US = "\x1f"


def rec(sha, ts, author, subject, body):
    return f"{RS}{sha}{US}{ts}{US}{author}{US}{subject}\n\n{body}"


def test_parse_single_delete_commit_with_numstat():
    text = rec(
        "a" * 40,
        1700000000,
        "joe",
        "chore: remove old thing",
        ":100644 000000 2aed677 0000000 D\told/thing.py\n0\t42\told/thing.py\n",
    )
    commits = parse_log(text)
    assert len(commits) == 1
    c = commits[0]
    assert c.sha == "a" * 40
    assert c.ts == 1700000000
    assert c.author == "joe"
    assert c.subject == "chore: remove old thing"
    assert c.changes == [Change("D", "old/thing.py")]
    assert c.deleted_lines == {"old/thing.py": 42}


def test_parse_rename_and_add_and_modify():
    body = (
        ":100644 100644 aaa bbb R100\tsrc/a.py\tsrc/b.py\n"
        ":000000 100644 000 ccc A\tnew.py\n"
        ":100644 100644 ddd eee M\tREADME.md\n"
        "0\t0\tsrc/{a.py => b.py}\n"
        "10\t0\tnew.py\n"
        "1\t1\tREADME.md\n"
    )
    (c,) = parse_log(rec("b" * 40, 1, "joe", "refactor: move", body))
    assert c.changes == [
        Change("R", "src/b.py", old_path="src/a.py"),
        Change("A", "new.py"),
        Change("M", "README.md"),
    ]
    # every numstat row is recorded; the walker only ever looks up paths from D rows
    assert c.deleted_lines["new.py"] == 0
    assert c.deleted_lines["README.md"] == 1
    assert c.deleted_lines["src/{a.py => b.py}"] == 0


def test_parse_binary_numstat_is_none():
    body = ":100644 000000 aaa 000 D\timg.png\n-\t-\timg.png\n"
    (c,) = parse_log(rec("c" * 40, 1, "joe", "rm image", body))
    assert c.deleted_lines == {"img.png": None}


def test_parse_multiple_commits_and_merge_without_diff():
    text = rec("1" * 40, 10, "a", "first", ":000000 100644 0 1 A\tx\n5\t0\tx\n") + rec(
        "2" * 40, 20, "b", "Merge branch 'x'", ""
    )
    commits = parse_log(text)
    assert [c.ts for c in commits] == [10, 20]
    assert commits[1].changes == []


def test_parse_quoted_path_with_space_and_escape():
    body = ':100644 000000 aaa 000 D\t"weird name\\tfile.txt"\n0\t3\t"weird name\\tfile.txt"\n'
    (c,) = parse_log(rec("d" * 40, 1, "joe", "rm", body))
    assert c.changes == [Change("D", "weird name\tfile.txt")]
    assert c.deleted_lines == {"weird name\tfile.txt": 3}


def test_parse_subject_with_unicode_and_empty_subject():
    (c,) = parse_log(rec("e" * 40, 1, "joe", "", ""))
    assert c.subject == ""
    (c2,) = parse_log(rec("f" * 40, 1, "joe", "chore(outputs): clean — housekeeping", ""))
    assert "housekeeping" in c2.subject


def test_read_log_reports_missing_git_as_giterror(tmp_path, monkeypatch):
    import subprocess

    from git_epitaph.gitlog import GitError, read_log

    def no_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    with pytest.raises(GitError, match="git not found on PATH"):
        read_log(tmp_path)


def test_unquote_handles_octal_and_plain():
    assert unquote("plain/path.py") == "plain/path.py"
    assert unquote('"caf\\303\\251.txt"') == "café.txt"
    assert unquote('"a\\"b"') == 'a"b'
