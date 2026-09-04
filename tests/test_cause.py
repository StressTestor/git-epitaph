import pytest

from git_epitaph.cause import cause_of_death


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("refactor(core): drop legacy parser", "refactored out of existence"),
        ("refactor!: big bang", "refactored out of existence"),
        ("chore: remove temp files", "swept up in a chore"),
        ("fix(auth): delete broken shim", "was the bug"),
        ("feat: replace old cli", "made room for a feature"),
        ("revert: undo the thing", "reverted, never happened"),
        ("docs: prune stale guide", "documentation casualty"),
        ("test: drop flaky spec", "test casualty"),
        ("ci: remove travis", "build system cleanup"),
        ("build: remove travis", "build system cleanup"),
        ("perf: cut slow path", "sacrificed for speed"),
        ("security: remove hardcoded key", "removed for your safety"),
        ("style: tidy", "cosmetic complications"),
    ],
)
def test_conventional_types(subject, expected):
    assert cause_of_death(subject) == expected


@pytest.mark.parametrize(
    "subject",
    [
        "Remove old parser",
        "delete unused assets",
        "rm cruft",
        "Clean up outputs",
        "cleanup: purge caches",
        "Drop dead code",
        "prune stale things",
    ],
)
def test_plain_removal_keywords(subject):
    assert cause_of_death(subject) == "deliberately removed"


def test_git_native_revert_subject():
    assert cause_of_death('Revert "feat: add the thing"') == "reverted, never happened"
    # only git's exact shape; a sentence starting with the word is not a revert
    assert cause_of_death("Revert to the old approach") == "unknown causes"


def test_wip_and_unknown():
    assert cause_of_death("wip") == "died of wip"
    assert cause_of_death("WIP: half done") == "died of wip"
    assert cause_of_death("Update stuff") == "unknown causes"
    assert cause_of_death("") == "unknown causes"
