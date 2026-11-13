"""Regressions from the final review before 0.1.0 (polishing round 5)."""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

from helpers import version, write
from test_review import doc, project

import arxiv_diff
from arxiv_diff.cli import main
from arxiv_diff.diff import compare, diff_authors, number_changes
from arxiv_diff.paper import load
from arxiv_diff.report import text


def test_a_declared_iflatexml_keeps_the_paper(tmp_path: Path) -> None:
    """\\newif\\iflatexml declared the switch, and the reader blanked everything after it."""
    a = write(tmp_path / "a")
    b = write(tmp_path / "b", BIG="28.9")
    main_tex = b / "main.tex"
    main_tex.write_text(main_tex.read_text(encoding="utf-8").replace("\\begin{document}", "\\newif\\iflatexml\n\\begin{document}"), encoding="utf-8")
    d = compare(load(a), load(b))
    assert d.summary.words_new == d.summary.words_old > 50
    assert d.summary.text_numbers_changed == 1


def test_iff_inside_the_latexml_branch(tmp_path: Path) -> None:
    body = "\\section{A}\nFirst sentence here. \\iflatexml $p \\iff q$ \\fi Second sentence here.\n"
    p = load(project(tmp_path / "p", {"main.tex": doc(body)}))
    assert [s.text for s in p.sections[1].sentences] == ["First sentence here.", "Second sentence here."]


def test_pairs_found_when_sentences_go_at_one_end_and_come_at_the_other(tmp_path: Path) -> None:
    """15 sentences removed at the start of a section, 15 added at its end, the 15 between lightly edited."""
    topics = ["graphene", "quasar", "enzyme", "glacier", "neutrino", "polymer", "volcano", "plankton", "magnet", "comet",
              "protein", "monsoon", "laser", "fossil", "isotope", "cortex", "aerosol", "lattice", "photon", "reef",
              "crystal", "galaxy", "virus", "dune", "turbine", "alloy", "bacteria", "pulsar", "sediment", "catalyst"]  # fmt: skip
    old = [f"The {t} sample was measured in the first campaign of the season." for t in topics[:30]]
    new = [s.replace("first campaign", "first long campaign") for s in old[15:]] + [f"An extra note on {t}." for t in "abcdefghijklmno"]
    a = project(tmp_path / "a", {"main.tex": doc("\\section{A}\n" + " ".join(old) + "\n")})
    b = project(tmp_path / "b", {"main.tex": doc("\\section{A}\n" + " ".join(new) + "\n")})
    d = compare(load(a), load(b))
    assert d.summary.sentences_changed == 15 and d.summary.sentences_removed == 15 and d.summary.sentences_added == 15


def test_two_people_with_one_surname_and_initial() -> None:
    d = diff_authors(["Yu Zhang", "Wei Li"], ["Yu Zhang", "Yang Zhang", "Wei Li"])
    assert d.added == ["Yang Zhang"] and not d.removed and not d.reordered
    assert not diff_authors(["E. Elmakies"], ["Elad Elmakies"]).changed


def test_names_that_are_also_institutions(tmp_path: Path) -> None:
    folder = project(tmp_path / "p", {"main.tex": doc("Text here.", "\\author{Ada Lovelace, Mila Nikolova, and Charles Babbage \\and Yale Song}\n")})
    assert load(folder).authors == ["Ada Lovelace", "Mila Nikolova", "Charles Babbage", "Yale Song"]


def test_money_and_results_written_in_math_mode() -> None:
    (n,) = number_changes("We spent $500 on data and $300 on compute.", "We spent $700 on data and $300 on compute.")
    assert (n.old, n.new) == ("500", "700")
    (n,) = number_changes(r"It is $3\times$ faster than before.", r"It is $4\times$ faster than before.")
    assert (n.old, n.new) == ("3", "4")
    (n,) = number_changes(r"The best is $\mathbf{91.2}$ on the set.", r"The best is $\mathbf{92.5}$ on the set.")
    assert (n.old, n.new) == ("91.2", "92.5")
    (n,) = number_changes(r"With $x^2$ and 84 percent.", r"With $x^2$ and 85 percent.")
    assert "⟨math⟩" not in n.before and n.before.endswith("and")


def test_no_hash_without_numbers_to_show(tmp_path: Path) -> None:
    a = project(tmp_path / "a", {"main.tex": doc("\\section{A}\nThe energy grows as $x^2$ for small values.\n")})
    b = project(tmp_path / "b", {"main.tex": doc("\\section{A}\nThe energy grows as $x^3$ for small values.\n")})
    (c,) = compare(load(a), load(b)).sections[1].changes
    assert c.kind == "changed" and not c.numbers and not c.numbers_only


def test_a_folder_above_the_paper_names_the_main_file(tmp_path: Path) -> None:
    write(tmp_path / "papers" / "v1")
    b = write(tmp_path / "b", BIG="28.9")
    out = io.StringIO()
    with redirect_stdout(out):
        assert main([str(tmp_path / "papers"), str(b), "--color", "never"]) == 0
    assert re.search(r"papers \(v1/main\.tex\) → ", out.getvalue())


def test_the_version_is_said_once() -> None:
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")  # tomllib is 3.11+
    assert re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1) == arxiv_diff.__version__  # type: ignore[union-attr]
    assert f"## {arxiv_diff.__version__}" in (Path(__file__).parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")


def test_the_example_still_reads_as_before(tmp_path: Path) -> None:
    d = compare(version(tmp_path, "v1"), version(tmp_path, "v2", BIG="28.9"))
    assert "Transformer (big) · EN-DE: 28.4 → 28.9  (+0.5, better)" in text(d)
