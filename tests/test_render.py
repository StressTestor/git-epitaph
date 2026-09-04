import json

from git_epitaph.render import fit_path, render_list, render_stones, summary, to_json
from git_epitaph.walk import Grave

DAY = 86400
T0 = 1_700_000_000  # 2023-11-14


def grave(path="src/old_parser.py", born=T0, died=T0 + 400 * DAY, lines=312, **kw):
    base = dict(
        path=path,
        born_path=path,
        born=born,
        born_sha="a" * 40 if born is not None else None,
        died=died,
        died_sha="d" * 40,
        killer="joe",
        epitaph="refactor(core): drop legacy parser",
        lines=lines,
        risen=False,
        aliases=[],
    )
    base.update(kw)
    return Grave(**base)


def test_fit_path_keeps_tail_when_too_long():
    assert fit_path("src/old_parser.py", 20) == "src/old_parser.py"
    out = fit_path("very/deep/directory/structure/file.py", 16)
    assert len(out) <= 16
    assert out.endswith("file.py")
    assert out.startswith("…")


def test_stone_contains_core_facts_and_is_rectangular():
    out = render_stones([grave()], width=40)
    assert "R.I.P." in out
    assert "old_parser.py" in out
    assert "312 lines" in out
    assert "2023-11-14" in out
    assert "2024-12-18" in out
    # the cause wraps across two stone rows
    assert "refactored out of" in out
    assert "existence" in out
    lines = out.splitlines()
    widths = {len(line) for line in lines if line.strip()}
    # every non-empty line of a single stone column has the same width
    assert len(widths) == 1


def test_stones_lay_out_in_columns_by_width():
    graves = [grave(path=f"f{i}.py") for i in range(4)]
    narrow = render_stones(graves, width=30)
    wide = render_stones(graves, width=200)
    assert len(narrow.splitlines()) > len(wide.splitlines())
    for i in range(4):
        assert f"f{i}.py" in wide


def test_stone_marks_risen_and_unknown_birth_and_binary():
    out = render_stones(
        [grave(risen=True, born=None, born_sha=None, lines=None)],
        width=40,
    )
    assert "RISEN" in out
    assert "????-??-??" in out
    assert "binary" in out


def test_render_list_has_resurrection_command():
    out = render_list([grave()])
    assert "src/old_parser.py" in out
    assert "git checkout dddddddddddd^ -- 'src/old_parser.py'" in out
    assert "killed by joe" in out
    assert "400 days" in out


def test_render_list_shows_aliases():
    out = render_list([grave(born_path="src/parser.py", aliases=["src/parser.py"])])
    assert "born as src/parser.py" in out


def test_to_json_roundtrips_fields():
    data = json.loads(to_json([grave()]))
    assert data[0]["path"] == "src/old_parser.py"
    assert data[0]["lines"] == 312
    assert data[0]["died_sha"] == "d" * 40
    assert data[0]["cause"] == "refactored out of existence"
    assert data[0]["age_days"] == 400
    assert data[0]["born_iso"] == "2023-11-14"


def test_summary_counts():
    s = summary([grave(), grave(risen=True), grave(lines=None)])
    assert "3 buried" in s
    assert "1 risen" in s
    assert "624 lines" in s
