"""Regressions from the independent code review of 2026-11-13: each test is the reproducer the review gave."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from helpers import write
from test_cli import FakeArxiv

from arxiv_diff.cli import main
from arxiv_diff.diff import compare
from arxiv_diff.paper import load
from arxiv_diff.report import markdown, text


def project(folder: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        p = folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return folder


def doc(body: str, preamble: str = "") -> str:
    return "\\documentclass{article}\n" + preamble + "\\begin{document}\n" + body + "\n\\end{document}\n"


def table(cols: list[str], rows: list[list[str]], label: str = "tab:a", caption: str = "Results.") -> str:
    head = " & ".join(cols) + " \\\\\n\\midrule\n"
    body = "".join(" & ".join(r) + " \\\\\n" for r in rows)
    label_ = f"\\label{{{label}}}" if label else ""
    tabular = f"\\begin{{tabular}}{{{'l' * len(cols)}}}\n\\toprule\n{head}{body}\\bottomrule\n\\end{{tabular}}\n"
    return f"\\begin{{table}}\\caption{{{caption}}}{label_}\n{tabular}\\end{{table}}\n"


def test_columns_alike_in_name_only_are_not_one_column(tmp_path: Path) -> None:
    """EN-DE and EN-RO, Acc@1 and Acc@5: half the words in common, none of the numbers."""
    a = project(tmp_path / "a", {"main.tex": doc(table(["Model", "EN-DE", "EN-FR"], [["Ours", "28.4", "41.0"], ["Base", "27.3", "38.1"]]))})
    b = project(tmp_path / "b", {"main.tex": doc(table(["Model", "EN-FR", "EN-RO"], [["Ours", "41.0", "34.2"], ["Base", "38.1", "33.0"]]))})
    (t,) = compare(load(a), load(b)).tables
    assert not t.cells and not t.columns_renamed
    assert t.columns_removed == ["EN-DE"] and t.columns_added == ["EN-RO"]
    c = project(tmp_path / "c", {"main.tex": doc(table(["Model", "Acc@1"], [["ResNet", "76.1"], ["ViT", "79.9"]]))})
    e = project(tmp_path / "e", {"main.tex": doc(table(["Model", "Acc@5"], [["ResNet", "92.9"], ["ViT", "95.0"]]))})
    (t,) = compare(load(c), load(e)).tables
    assert not t.cells and t.columns_added == ["Acc@5"]


def test_on_a_tie_the_first_table_is_the_old_one(tmp_path: Path) -> None:
    """An unchanged table, and a new one with the same caption after it."""
    first = table(["Variant", "Score"], [["full model", "80.1"], ["no attention", "71.2"]], label="", caption="Ablation results.")
    second = table(["Variant", "Score"], [["no dropout", "78.3"], ["no warmup", "79.0"]], label="", caption="Ablation results.")
    a = project(tmp_path / "a", {"main.tex": doc("\\section{R}\nText.\n" + first)})
    b = project(tmp_path / "b", {"main.tex": doc("\\section{R}\nText.\n" + first + second)})
    assert [t.status for t in compare(load(a), load(b)).tables] == ["same", "added"]


def test_authors_in_any_script(tmp_path: Path) -> None:
    a = project(tmp_path / "a", {"main.tex": doc("Text here.", "\\author{Иван Петров \\and Анна Смирнова}\n")})
    b = project(tmp_path / "b", {"main.tex": doc("Text here.", "\\author{Иван Петров \\and Олег Козлов}\n")})
    d = compare(load(a), load(b))
    assert d.authors.added == ["Олег Козлов"] and d.authors.removed == ["Анна Смирнова"] and d.changed


@pytest.mark.parametrize(
    "files",
    [
        # each file \input-s the next four times, twelve deep: 4^12 copies if nothing stopped it
        {f"f{k}.tex": "x\n" + f"\\input{{f{k + 1}}}\n" * 4 for k in range(12)} | {"main.tex": doc("\\section{A}\n\\input{f0}\n")},
        # a command that expands into itself many times
        {"main.tex": doc("\\section{A}\nWe use \\x here.\n", "\\newcommand{\\x}{" + "\\x" * 60 + "}\n")},
        # one paragraph of 1.5 MB, and 8000 unclosed \(
        {"main.tex": doc("\\section{A}\n" + "Some words here. " * 90_000)},
        {"main.tex": doc("\\section{A}\n" + "A \\( b. C d. " * 8000)},
        # unclosed environments, many times
        {"main.tex": doc("\\section{A}\n" + "\\begin{equation} x. Y z. " * 5000 + "\\begin{figure} a. B c. " * 5000)},
    ],
    ids=["input-fan-out", "self-recursive-command", "long-paragraph", "unclosed-math", "unclosed-environments"],
)
def test_hostile_sources_are_read_quickly(tmp_path: Path, files: dict[str, str]) -> None:
    folder = project(tmp_path / "p", files)
    start = time.perf_counter()
    paper = load(folder)
    compare(paper, paper)
    assert time.perf_counter() - start < 10, "a hostile source must not make it hang"


def test_json_keeps_the_arxiv_title(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeArxiv(tmp_path)
    assert main(["2501.00001v2", "--format", "json"], client=fake.client()) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["arxiv_title"] == "Attention Is All You Need" and report["title"] is None  # the paper's title did not change


def test_all_reports_the_steps_that_could_be_compared(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeArxiv(tmp_path)
    fake.sources[3] = b"%PDF-1.5 ..."
    assert main(["2501.00001", "--all", "--format", "json"], client=fake.client()) == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert (report["old_version"], report["new_version"]) == (1, 2)
    assert "not compared: v2 → v3" in captured.err and "PDF only" in captured.err


def test_summary_lines_show_no_markdown_escapes(tmp_path: Path) -> None:
    """Inside <details>, GitHub does not read Markdown: "\\~1" would show with its backslash."""
    from helpers import version

    md = markdown(compare(version(tmp_path, "v1"), version(tmp_path, "v2", METHOD="My_Model")))
    summaries = [line for line in md.splitlines() if line.startswith("<summary>")]
    assert summaries and all("\\" not in line for line in summaries)
    assert "<summary>changed: 2 My_Model (was 2 Model) — +0 -0 ~0</summary>" in summaries


def test_no_empty_sections_heading_and_no_missing_input_as_text(tmp_path: Path) -> None:
    a = project(
        tmp_path / "a", {"main.tex": doc("\\section{R}\nText here is fine.\n\\input{sections/missing}\n" + table(["M", "X"], [["a", "1.0"]]))}
    )
    b = project(
        tmp_path / "b", {"main.tex": doc("\\section{R}\nText here is fine.\n\\input{sections/missing}\n" + table(["M", "X"], [["a", "2.0"]]))}
    )
    pa = load(a)
    assert [s.text for s in pa.sections[1].sentences] == ["Text here is fine."]
    out = text(compare(pa, load(b)))
    assert "Tables" in out and "Sections" not in out


def test_the_example_still_has_its_changes(tmp_path: Path) -> None:
    """The review's fixes keep the real cases: the example's two versions."""
    root = Path(__file__).parent.parent / "examples"
    d = compare(load(root / "v1"), load(root / "v2"))
    assert [(c.row, c.old, c.new) for t in d.tables for c in t.cells if c.kind == "value"] == [("TinyFormer", "31.2", "30.8")]
    assert write  # the helpers stay importable
