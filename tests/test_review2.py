"""Regressions from the second independent review (reports, the HTML page, the docs) and from measuring 16 more
papers in polishing round 2."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from helpers import version, write
from test_cli import FakeArxiv
from test_review import doc, project, table

from arxiv_diff.cli import main
from arxiv_diff.diff import compare
from arxiv_diff.html import page
from arxiv_diff.paper import load
from arxiv_diff.report import markdown, text


def test_a_result_replaced_by_text_and_a_number_beside_an_added_one(tmp_path: Path) -> None:
    """41.0 -> "--" in a table, and "28.4 BLEU" -> "28.9 (std 0.2) BLEU" in a sentence, are changed results."""
    a = project(
        tmp_path / "a", {"main.tex": doc("\\section{R}\nWe reach 28.4 BLEU on the test set.\n" + table(["Model", "EN-FR"], [["Ours", "41.0"]]))}
    )
    b = project(
        tmp_path / "b",
        {"main.tex": doc("\\section{R}\nWe reach 28.9 (std 0.2) BLEU on the test set.\n" + table(["Model", "EN-FR"], [["Ours", "--"]]))},
    )
    d = compare(load(a), load(b))
    assert d.summary.table_values_changed == 1 and d.summary.text_numbers_changed == 1
    assert [(n.old, n.new) for sd in d.sections for c in sd.changes for n in c.numbers] == [("28.4", "28.9")]
    assert main([str(a), str(b), "--fail-on", "results"]) == 1


def test_sections_that_only_swapped_places_are_a_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    one, two = "\\section{Data}\nWe use a large corpus of web text.\n", "\\section{Model}\nOur model is a deep transformer network.\n"
    a = project(tmp_path / "a", {"main.tex": doc(one + two)})
    b = project(tmp_path / "b", {"main.tex": doc(two + one)})
    d = compare(load(a), load(b))
    assert d.changed and any(sd.moved for sd in d.sections)
    assert "(moved)" in text(d) and "section moved" in text(d)
    assert main([str(a), str(b), "--fail-on", "any"]) == 1


def test_better_or_worse_only_where_the_metric_says(tmp_path: Path) -> None:
    caption = "Model sizes; the best is in bold."
    a = project(tmp_path / "a", {"main.tex": doc(table(["Model", "Layers", "Error (\\%)"], [["Ours", "6", "4.1 $\\pm$ 0.2"]], caption=caption))})
    b = project(tmp_path / "b", {"main.tex": doc(table(["Model", "Layers", "Error (\\%)"], [["Ours", "12", "4.1 $\\pm$ 0.5"]], caption=caption))})
    (t,) = compare(load(a), load(b)).tables
    layers = next(c for c in t.cells if c.column == "Layers")
    error = next(c for c in t.cells if c.column.startswith("Error"))
    assert layers.kind == "value" and layers.better is None  # "is" in the caption is not a metric
    assert error.kind == "text" and not error.result  # only the spread changed


def test_control_characters_in_file_names_are_shown_not_sent(tmp_path: Path) -> None:
    fig = "\\begin{figure}\\includegraphics{plot%s}\\caption{A plot.}\\label{fig:a}\\end{figure}"
    a = project(tmp_path / "a", {"main.tex": doc("\\section{A}\nText here.\n" + fig % "one")})
    b = project(tmp_path / "b", {"main.tex": doc("\\section{A}\nText here.\n" + fig % "\x1b[2Jtwo")})
    out = text(compare(load(a), load(b)))
    assert "\x1b" not in out and "\\x1b[2J" in out


def test_markdown_numbers_only_lines_are_not_headings(tmp_path: Path) -> None:
    md = markdown(compare(version(tmp_path, "v1"), version(tmp_path, "v2", BIG="28.9")))
    assert not re.search(r"^- #", md, re.M)
    assert "- **\\#** On the WMT 2014" in md
    assert "#### Numbers in the text" in md and "~~28.4~~ **28.9**" in md


def test_an_unexpected_error_is_exit_2(tmp_path: Path) -> None:
    out_dir = tmp_path / "a-folder"
    out_dir.mkdir()
    assert main([str(write(tmp_path / "a")), str(write(tmp_path / "b")), "-o", str(out_dir)]) == 2  # -o is a folder


def test_one_version_gives_json_still(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeArxiv(tmp_path)
    fake.get_record = fake.get  # one version only
    single = '<version version="v2">'
    fake_record = (Path(__file__).parent / "test_cli.py").read_text(encoding="utf-8")
    assert single in fake_record  # the fake record has v1..v3; make it one version
    import test_cli

    one = test_cli.OAI.split('<version version="v2">')[0] + "</arXivRaw></metadata></record></GetRecord></OAI-PMH>"
    fake.get = lambda url: one.encode() if "oai2" in url else fake.sources[1]  # type: ignore[method-assign]
    out = tmp_path / "r.json"
    assert main(["2501.00001", "--format", "json", "-o", str(out)], client=fake.client()) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == []
    assert "only one version" in capsys.readouterr().err


def test_html_filters_titles_and_policy(tmp_path: Path) -> None:
    v1, v2, v3 = version(tmp_path, "v1"), version(tmp_path, "v2", BIG="28.9", CAPTION="The Transformer."), version(tmp_path, "v3", BIG="29.1")
    html = page([(compare(v1, v2), "")])
    assert "pair caption" in html and "no-numbers" in html and 'id="d0-numbers"' in html
    assert "script-src 'sha256-" in html and "script-src 'unsafe-inline'" not in html
    assert "1 sentences" not in html
    two = page([(compare(v1, v2), ""), (compare(v2, v3), "")])
    assert "<title>arxiv-diff: v1 → v3, 2 steps</title>" in two


def test_terminal_caption_word_diff_and_headline_rows(tmp_path: Path) -> None:
    out = text(
        compare(version(tmp_path, "v1"), version(tmp_path, "v2", ROWS=r"Transformer (base) & 27.3 & 38.1 \\", CAPTION="The full model architecture."))
    )
    assert "1 table row added" in out
    assert "caption: The {+full+} model architecture." in out


def test_full_shows_the_sentences_of_an_added_section(tmp_path: Path) -> None:
    d = compare(version(tmp_path, "v1"), version(tmp_path, "v2", EXTRA="\\section{Analysis}\nWe also tried smaller models, which were worse.\n"))
    assert "We also tried smaller models" not in text(d) and "We also tried smaller models" in text(d, limit=0)


@pytest.mark.parametrize(
    ("block", "names"),
    [
        # the survey 2209.00796 v1: names separated by escaped spaces
        (
            r"Ling Yang\textsuperscript{1}\ \ \ \ \ Zhilong  Zhang\textsuperscript{1}\ \ \ \ \ Shenda Hong \\ Peking University",
            ["Ling Yang", "Zhilong Zhang", "Shenda Hong"],
        ),
        # ControlNet 2302.05543 v1: the names in \texttt
        (r"\texttt{Lvmin Zhang and Maneesh Agrawala}\\\texttt{Stanford University}", ["Lvmin Zhang", "Maneesh Agrawala"]),
    ],
)
def test_authors_from_the_second_measurement(tmp_path: Path, block: str, names: list[str]) -> None:
    folder = project(tmp_path / "p", {"main.tex": doc("Text here.", f"\\author{{{block}}}\n")})
    assert load(folder).authors == names


def test_numbers_now_under_another_header_are_pointed_out(tmp_path: Path) -> None:
    """From BLIP-2 v1 -> v3: the VQAv2 columns "val, test-dev" were relabelled "test-dev, test-std", same numbers."""
    rows = [["ALBEF", "75.84", "76.04"], ["BLIP", "78.25", "78.32"], ["Flamingo", "82.00", "82.10"]]
    a = project(tmp_path / "a", {"main.tex": doc(table(["Model", "val", "test-dev"], rows))})
    b = project(tmp_path / "b", {"main.tex": doc(table(["Model", "test-dev", "test-std"], rows))})
    (t,) = compare(load(a), load(b)).tables
    assert t.columns_moved == [("val", "test-dev"), ("test-dev", "test-std")]
    assert "numbers now under another header: val → test-dev; test-dev → test-std" in text(compare(load(a), load(b)))


def test_a_fully_rewritten_section_is_compared_quickly(tmp_path: Path) -> None:
    """Round 4: every sentence of long sections rewritten cost a square of comparisons per section (43 s for 100
    sections of 60 sentences); now a band near each sentence's place, each sentence tokenized once."""
    import random
    import time

    vocab = "model data attention layer training results improves baseline accuracy method task network".split()

    def section(edit: bool) -> str:
        out = []
        for k in range(60):
            words = " ".join(random.Random(k).choice(vocab) for _ in range(16))
            out.append(f"{words.capitalize()} {'now ' if edit else ''}reaches {k}.{k + int(edit)} points.")
        return "\\section{A}\n" + "\n".join(out) + "\n"

    a = project(tmp_path / "a", {"main.tex": doc(section(False) * 5)})
    b = project(tmp_path / "b", {"main.tex": doc(section(True) * 5)})
    pa, pb = load(a), load(b)
    start = time.perf_counter()
    d = compare(pa, pb)
    assert time.perf_counter() - start < 5
    assert d.summary.sentences_changed == 300 and d.summary.sentences_added == d.summary.sentences_removed == 0
