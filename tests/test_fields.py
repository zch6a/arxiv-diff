"""Regressions from measuring 20 papers outside machine learning (polishing round 3): physics, mathematics,
astronomy, neuroscience, economics, statistics."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_review import doc, project

from arxiv_diff.diff import compare, number_changes
from arxiv_diff.paper import load


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # formulas: coefficients, exponents and fractions are not results (Yang-Mills-Higgs, quantum criticality)
        (r"Then $\frac 12 (1-|x|^2)$ holds for all $t$.", r"Then $\frac{1}{2}(1-|x|^2)$ holds for all $t$."),
        (r"We set $\coloneqq -\frac{2}{27} - 14 \ln 2$ here.", r"We set $\coloneqq -\frac{17}{18} - 3 \ln 2$ here."),
        # a reference to a numbered label (turbulence: "(G8)" -> "(G12)")
        (r"as shown in Eq.~\eqref{G8}, the flux grows.", r"as shown in Eq.~\eqref{G12}, the flux grows."),
        # a DOI (neuroscience: the code's Zenodo record)
        (r"Code at doi:10.5281/zenodo.23044669 (version 1.1.0).", r"Code at doi:10.5281/zenodo.24106761 (version 1.1.0)."),
    ],
    ids=["fraction", "coefficients", "reference-label", "doi"],
)
def test_numbers_that_are_formulas_labels_or_identifiers(tmp_path: Path, old: str, new: str) -> None:
    a = project(tmp_path / "a", {"main.tex": doc("\\section{A}\n" + old + "\n")})
    b = project(tmp_path / "b", {"main.tex": doc("\\section{A}\n" + new + "\n")})
    d = compare(load(a), load(b))
    assert d.summary.text_numbers_changed == 0
    assert d.summary.sentences_changed == 1  # the edit itself is still reported


def test_numbers_in_math_mode_are_still_results() -> None:
    """Papers write results in math mode too ("by more than $2.0$ BLEU")."""
    (n,) = number_changes(r"a score of $28.4$ on the test set", r"a score of $28.9$ on the test set")
    assert (n.old, n.new) == ("28.4", "28.9")
    (n,) = number_changes("about 84 percent of the weighted index", "about 85 percent of the weighted index")
    assert (n.old, n.new) == ("84", "85")


def test_a_displayed_equation_has_no_numbers_in_the_text(tmp_path: Path) -> None:
    eq = "\\section{A}\nWe find\n\\begin{equation}\n  E = %s m c^2\n\\end{equation}\n"
    d = compare(load(project(tmp_path / "a", {"main.tex": doc(eq % "1")})), load(project(tmp_path / "b", {"main.tex": doc(eq % "2")})))
    assert d.summary.sentences_changed == 1 and d.summary.text_numbers_changed == 0


def test_elsevier_marks_and_initials(tmp_path: Path) -> None:
    """Economics (elsarticle): \\corref{cor1} after a name; fluid dynamics: "E. Elmakies" in v1, "Elad Elmakies" in v6."""
    a = project(
        tmp_path / "a", {"main.tex": doc("Text here.", "\\author[1]{Piyush Akimitsu\\corref{cor1}}\n\\author{E. Elmakies \\and O. Shildkrot}\n")}
    )
    b = project(tmp_path / "b", {"main.tex": doc("Text here.", "\\author[1]{Piyush Akimitsu}\n\\author{Elad Elmakies \\and Oleg Shildkrot}\n")})
    pa, pb = load(a), load(b)
    assert pa.authors == ["Piyush Akimitsu", "E. Elmakies", "O. Shildkrot"]
    assert not compare(pa, pb).authors.changed


def test_names_typed_without_author_and_the_latexml_branch(tmp_path: Path) -> None:
    """Economics v2 typed its title block twice (\\iflatexml for arXiv's HTML, \\else for the PDF) and its authors
    without \\author: the block is read once, and the authors are said to be unread, not removed."""
    from arxiv_diff.report import text

    block = "\\iflatexml\n{\\large Where Has It Gone?}\\\\ Piyush Akimitsu\n\\else\n{\\large Where Has It Gone?}\\\\ Piyush Akimitsu\n\\fi\n"
    a = project(tmp_path / "a", {"main.tex": doc("\\section{A}\nText here.\n", "\\author{Piyush Akimitsu}\n")})
    b = project(tmp_path / "b", {"main.tex": doc(block + "\\section{A}\nText here.\n")})
    pb = load(b)
    assert [s.text for s in pb.sections[0].sentences] == ["Where Has It Gone? Piyush Akimitsu"]  # once, not twice
    d = compare(load(a), pb)
    assert d.authors.unread == "new" and not d.authors.removed
    assert "authors: none found in b (written without \\author?), so not compared" in text(d)
