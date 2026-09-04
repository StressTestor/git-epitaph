from git_epitaph.gitlog import Change, Commit
from git_epitaph.walk import bury

DAY = 86400


def commit(sha, ts, subject, changes, deleted=None, author="joe"):
    return Commit(
        sha=sha,
        ts=ts,
        author=author,
        subject=subject,
        changes=changes,
        deleted_lines=deleted or {},
    )


def test_add_then_delete_produces_one_grave_with_birth():
    commits = [
        commit("a1", 0, "feat: add x", [Change("A", "x.py")]),
        commit("d1", 3 * DAY, "chore: rm x", [Change("D", "x.py")], {"x.py": 12}),
    ]
    (g,) = bury(commits)
    assert g.path == "x.py"
    assert g.born_path == "x.py"
    assert g.born == 0
    assert g.born_sha == "a1"
    assert g.died == 3 * DAY
    assert g.died_sha == "d1"
    assert g.killer == "joe"
    assert g.epitaph == "chore: rm x"
    assert g.lines == 12
    assert g.age_days == 3
    assert g.risen is False
    assert g.aliases == []


def test_rename_carries_birth_forward_and_is_not_a_death():
    commits = [
        commit("a1", 0, "add", [Change("A", "old.py")]),
        commit("r1", DAY, "move", [Change("R", "new.py", old_path="old.py")]),
        commit("d1", 5 * DAY, "rm", [Change("D", "new.py")], {"new.py": 3}),
    ]
    (g,) = bury(commits)
    assert g.path == "new.py"
    assert g.born_path == "old.py"
    assert g.born == 0
    assert g.aliases == ["old.py"]
    assert g.age_days == 5


def test_readded_file_marks_previous_grave_risen_and_can_die_again():
    commits = [
        commit("a1", 0, "add", [Change("A", "x")]),
        commit("d1", DAY, "rm", [Change("D", "x")], {"x": 1}),
        commit("a2", 2 * DAY, "revert: bring back x", [Change("A", "x")]),
        commit("d2", 4 * DAY, "rm again", [Change("D", "x")], {"x": 2}),
    ]
    graves = bury(commits)
    assert len(graves) == 2
    first, second = graves
    assert first.risen is True
    assert first.died_sha == "d1"
    assert second.risen is False
    assert second.born_sha == "a2"
    assert second.age_days == 2


def test_delete_without_known_birth_is_unknown_born():
    # e.g. shallow clone: the file existed before history starts
    commits = [commit("d1", DAY, "rm", [Change("D", "ghost.py")], {"ghost.py": 7})]
    (g,) = bury(commits)
    assert g.born is None
    assert g.born_sha is None
    assert g.born_path == "ghost.py"
    assert g.age_days is None


def test_copy_starts_a_fresh_birth_for_the_copy():
    commits = [
        commit("a1", 0, "add", [Change("A", "a")]),
        commit("c1", DAY, "copy", [Change("C", "b", old_path="a")]),
        commit("d1", 2 * DAY, "rm b", [Change("D", "b")], {"b": 1}),
    ]
    (g,) = bury(commits)
    assert g.born_sha == "c1"
    assert g.born_path == "b"


def test_binary_delete_has_no_line_count():
    commits = [
        commit("a1", 0, "add", [Change("A", "img.png")]),
        commit("d1", DAY, "rm", [Change("D", "img.png")], {"img.png": None}),
    ]
    (g,) = bury(commits)
    assert g.lines is None


def test_rename_of_unknown_file_keeps_birth_unknown():
    # shallow history: we never saw old.py born, so the rename must not invent a birth
    commits = [
        commit("r1", DAY, "move", [Change("R", "new.py", old_path="old.py")]),
        commit("d1", 5 * DAY, "rm", [Change("D", "new.py")], {"new.py": 3}),
    ]
    (g,) = bury(commits)
    assert g.born is None
    assert g.born_sha is None
    assert g.age_days is None
    assert g.aliases == ["old.py"]


def test_rename_or_copy_onto_a_buried_path_marks_it_risen():
    commits = [
        commit("a1", 0, "add", [Change("A", "x"), Change("A", "y"), Change("A", "z")]),
        commit("d1", DAY, "rm x", [Change("D", "x")], {"x": 1}),
        commit("r1", 2 * DAY, "y -> x", [Change("R", "x", old_path="y")]),
        commit("d2", 3 * DAY, "rm x again", [Change("D", "x")], {"x": 1}),
        commit("c1", 4 * DAY, "copy z -> x", [Change("C", "x", old_path="z")]),
    ]
    graves = bury(commits)
    assert [g.risen for g in graves] == [True, True]


def test_living_paths_mark_graves_risen_when_replay_missed_the_return():
    # a merge resolution kept the file; plain git log shows no diff for the merge, so the
    # only evidence the file is alive is that it exists at HEAD
    commits = [
        commit("a1", 0, "add", [Change("A", "kept.py"), Change("A", "gone.py")]),
        commit("d1", DAY, "rm both", [Change("D", "kept.py"), Change("D", "gone.py")]),
    ]
    graves = bury(commits, living={"kept.py", "unrelated.py"})
    by_path = {g.path: g for g in graves}
    assert by_path["kept.py"].risen is True
    assert by_path["gone.py"].risen is False


def test_graves_are_ordered_by_death_time():
    commits = [
        commit("a1", 0, "add", [Change("A", "a"), Change("A", "b")]),
        commit("d1", DAY, "rm a", [Change("D", "a")], {"a": 1}),
        commit("d2", 2 * DAY, "rm b", [Change("D", "b")], {"b": 1}),
    ]
    assert [g.path for g in bury(commits)] == ["a", "b"]
