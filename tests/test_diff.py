from __future__ import annotations

from pathlib import Path

from helpers import version

from arxiv_diff.diff import compare


def test_identical_versions_have_no_changes(tmp_path: Path) -> None:
    d = compare(version(tmp_path, "v1"), version(tmp_path, "v2"))
    assert not d.changed
    assert all(sd.status == "same" for sd in d.sections)
    assert d.summary.words_old == d.summary.words_new > 50


def test_reads_the_paper(tmp_path: Path) -> None:
    p = version(tmp_path, "v1")
    assert p.title == "Attention Is All You Need"
    assert p.authors == ["Ada Lovelace", "Charles Babbage"]
    assert [s.name for s in p.sections] == ["", "1 Introduction", "2 Model", "3 Results", "4 Conclusion"]
    intro = p.sections[1]
    assert intro.file == "sections/intro.tex" and intro.line == 1
    assert intro.sentences[0].text == "Recurrent models process tokens one at a time [hochreiter1997]."
    assert [s.kind for s in p.sections[2].sentences] == ["text", "text", "equation"]
    assert [r.key for r in p.references] == ["hochreiter1997", "bahdanau2014"]  # luong2015 is not cited
    assert p.sections[0].sentences == []  # the title, authors and abstract are not prose of the first section


def test_a_changed_result_in_a_table_is_found_by_row_and_column(tmp_path: Path) -> None:
    a = version(tmp_path, "v1")
    b = version(tmp_path, "v2", BIG="28.9", ROWS=r"Transformer (base) & 27.3 & 38.1 \\")
    d = compare(a, b)
    (t,) = d.tables
    assert t.status == "changed" and t.name == "tab:main"
    (c,) = t.cells
    assert (c.row, c.column, c.old, c.new, c.kind) == ("Transformer (big)", "EN-DE", "28.4", "28.9", "value")
    assert c.delta == 0.5 and c.better is True  # BLEU (from the caption): higher is better
    assert t.rows_added == ["Transformer (base)"] and not t.rows_removed
    assert d.summary.table_values_changed == 1


def test_a_changed_number_in_a_sentence(tmp_path: Path) -> None:
    d = compare(version(tmp_path, "v1"), version(tmp_path, "v2", BIG="28.9"))
    results = next(sd for sd in d.sections if sd.name == "3 Results")
    (c,) = results.changes
    assert c.kind == "changed" and c.numbers_only
    assert [(n.old, n.new) for n in c.numbers] == [("28.4", "28.9")]
    assert ("-", " 28.4") in c.words and ("+", " 28.9") in c.words
    assert d.summary.text_numbers_changed == 1


def test_abstract_title_and_authors(tmp_path: Path) -> None:
    b = version(
        tmp_path,
        "v2",
        TITLE="Attention Is All You Need (Extended)",
        AUTHOR2="Charles Babbage \\And Grace Hopper",
        ABSTRACT="We propose a new architecture based on attention alone. It reaches 28.4 BLEU on English-to-German. It trains fast.",
    )
    d = compare(version(tmp_path, "v1"), b)
    assert d.title == ("Attention Is All You Need", "Attention Is All You Need (Extended)")
    assert d.authors.added == ["Grace Hopper"] and not d.authors.removed and not d.authors.reordered
    assert [c.kind for c in d.abstract] == ["changed", "added"]
    assert d.abstract[0].words[-2:] == [("+", " alone"), ("=", ".")]


def test_renamed_section_is_paired_with_its_old_self(tmp_path: Path) -> None:
    d = compare(version(tmp_path, "v1"), version(tmp_path, "v2", METHOD="Model Architecture"))
    sd = next(sd for sd in d.sections if sd.renamed)
    assert sd.old is not None and sd.new is not None
    assert (sd.old.name, sd.new.name, sd.status) == ("2 Model", "2 Model Architecture", "changed")
    assert not sd.changes and d.summary.sections_added == d.summary.sections_removed == 0


def test_added_section_and_moved_sentence(tmp_path: Path) -> None:
    extra = "\\section{Analysis}\nTraining took 3.5 days on 8 GPUs. We also tried smaller models, which were worse.\n"
    a = version(tmp_path, "v1")
    version(tmp_path, "v2", EXTRA=extra)
    # in v2 the sentence about training time is in Analysis as well as in Results; remove it from Results
    main = tmp_path / "v2" / "main.tex"
    main.write_text(main.read_text(encoding="utf-8").replace("BLEU. Training took 3.5 days on 8 GPUs.\n", "BLEU.\n"), encoding="utf-8")
    from arxiv_diff.paper import load

    d = compare(a, load(tmp_path / "v2", "v2"))
    names = [(sd.status, sd.name) for sd in d.sections]
    assert ("added", "4 Analysis") in names
    moved = [c for sd in d.sections for c in sd.changes if c.kind == "moved"]
    assert len(moved) == 2 and {c.other for c in moved} == {"3 Results", "4 Analysis"}
    assert d.summary.sentences_moved == 1 and d.summary.sections_added == 1


def test_figures_and_references(tmp_path: Path) -> None:
    b = version(
        tmp_path,
        "v2",
        FIG="model-v2",
        CAPTION="The Transformer architecture.",
        CITE="bahdanau2014, luong2015",
        VENUE="International Conference on Learning Representations",
        YEAR="2015",
    )
    d = compare(version(tmp_path, "v1"), b)
    (f,) = d.figures
    assert f.status == "changed" and f.graphics == (["model"], ["model-v2"])
    assert ("+", " Transformer") in f.caption
    assert [r.key for r in d.references.added] == ["luong2015"]
    (u,) = d.references.updated
    assert u.key == "bahdanau2014" and "now the published version" in u.what and "year 2014 → 2015" in u.what


VARIATIONS = r"""\documentclass{article}
\newcommand{\dff}{d_{\text{ff}}}
\begin{document}
\section{Results}
See Table~\ref{tab:var}.
\begin{table}\caption{Variations.}\label{tab:var}
\begin{tabular}{lccc}
\hline
 & $\dff$ & PPL & params \\
\hline
base & %DFF% & 4.92 & 65 \\
\hline\rule{0pt}{2.0ex}
\multirow{2}{*}{(A)}
& 512 & 5.29 & %P% \\
& 128 & 5.00 & %P% \\
\hline
\end{tabular}
\end{table}
\end{document}
"""


def _variations(folder: Path, dff: str, params: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "main.tex").write_text(VARIATIONS.replace("%DFF%", dff).replace("%P%", params), encoding="utf-8")
    return folder


def test_table_keys_read_as_printed(tmp_path: Path) -> None:
    """From Attention Is All You Need, v1 -> v7: a header that is a macro, names under \\multirow and \\rule,
    a corrected value, and cells cleared."""
    from arxiv_diff.diff import columns, rows
    from arxiv_diff.paper import load

    a = load(_variations(tmp_path / "v1", "1024", "65"), "v1")
    b = load(_variations(tmp_path / "v7", "2048", ""), "v7")
    assert columns(a.tables[0])[1] == r"$d_{\text{ff}}$"
    assert [k for _, k in rows(a.tables[0])] == ["base", "(A)", "(A) (2)"]
    (t,) = compare(a, b).tables
    value = [c for c in t.cells if c.kind == "value"]
    assert [(c.row, c.old, c.new) for c in value] == [("base", "1024", "2048")]
    assert [(c.row, c.old, c.new) for c in t.cells if c.kind == "text"] == [("(A)", "65", ""), ("(A) (2)", "65", "")]
    from arxiv_diff.report import text

    out = text(compare(a, b))
    assert "base · $d_{\\text{ff}}$: 1024 → 2048  (+1024)" in out
    assert "params: 2 cells emptied (was 65): (A); (A) (2)" in out


COCO = r"""\documentclass{article}
\begin{document}
\section{Results}
\begin{table}\caption{System-level comparison.}\label{exp:coco}
\setlength\tabcolsep{1.0pt}
\begin{tabular}{lcc}
\toprule
Method & SQuAD & RACE \\
\midrule
Swin-L (HTC++) & 57.1 & %RACE% \\
Swin-L (HTC++)* & 58.0 & 64.0 \\
ALBERT & %SQUAD% & 68.4 \\
\bottomrule
\end{tabular}
\end{table}
\end{document}
"""


def _coco(folder: Path, squad: str, race: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "main.tex").write_text(COCO.replace("%SQUAD%", squad).replace("%RACE%", race), encoding="utf-8")
    return folder


def test_marked_rows_and_cells_with_several_numbers(tmp_path: Path) -> None:
    """From Swin Transformer v1 -> v2 (a row and its starred twin, unchanged, were compared with each other) and
    ALBERT v1 -> v6 (the second number of "89.3/82.1" changed and nothing was reported)."""
    from arxiv_diff.diff import columns
    from arxiv_diff.paper import load

    a = load(_coco(tmp_path / "a", "89.3/82.1", "63.5"), "a")
    b = load(_coco(tmp_path / "b", "89.3/82.3", "63.5"), "b")
    assert columns(a.tables[0])[0] == "Method"  # \setlength\tabcolsep{1.0pt} is not part of the header
    (t,) = compare(a, b).tables
    assert [(c.row, c.old, c.new, c.kind, c.delta) for c in t.cells] == [("ALBERT", "89.3/82.1", "89.3/82.3", "value", 0.2)]
    same = load(_coco(tmp_path / "c", "89.3/82.1", "63.5"), "c")
    assert not compare(a, same).tables[0].cells


def test_a_table_whose_rows_were_all_renamed_is_still_paired(tmp_path: Path) -> None:
    """From GPT-3 v1 -> v4: every row's label went from "Completion" to "Target Completion"."""
    from arxiv_diff.paper import load

    def table(label: str) -> str:
        rows = "\n".join(f"{label} & answer {k} & {k}.0 \\\\" for k in range(1, 6))
        head = "\\documentclass{article}\\begin{document}\n\\begin{tabular}{lll}\nContext & Q & score \\\\\n\\midrule\n"
        return f"{head}{rows}\n\\end{{tabular}}\n\\end{{document}}\n"

    for name, label in (("a", "Completion"), ("b", "Target Completion")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.tex").write_text(table(label), encoding="utf-8")
    (t,) = compare(load(tmp_path / "a", "a"), load(tmp_path / "b", "b")).tables
    assert t.status == "changed" and not t.rows_added and not t.rows_removed and not t.cells
    assert t.rows_renamed[0] == ("Completion | answer 1", "Target Completion | answer 1") and len(t.rows_renamed) == 5


def test_numbers_that_are_not_changed_results() -> None:
    """From the measurement: a year inside a citation key (DDPM, ViT, GPT-3), the same number written another way
    (LoRA: 12288 -> 12,288, 4.6k -> 4,600), and a hyphen that is not a minus sign (ALiBi: WikiText-103)."""
    from arxiv_diff.diff import number_changes

    assert number_changes("importance sampling [huang2019evaluating].", "importance sampling [huang2020evaluating].") == []
    assert number_changes("as high as 12288, making", "as high as 12,288, making") == []
    assert number_changes("$4.6$k validation examples", "$4,600$ validation examples") == []
    assert number_changes("on WikiText-103 ALiBi is efficient", "on WikiText 103 ALiBi is efficient") == []
    (n,) = number_changes("from 14.8% to 17.3%", "from 14.3% to 17.3%")
    assert (n.old, n.new) == ("14.8", "14.3")


def test_a_cell_written_with_the_papers_own_command(tmp_path: Path) -> None:
    """From Chain-of-Thought v6: cells written \\cell{6.5}{0.4} (a command with arguments) are numbers."""
    from arxiv_diff.paper import load

    def paper(folder: Path, value: str) -> Path:
        folder.mkdir()
        body = (
            "\\begin{tabular}{lc}\nMethod & GSM8K \\\\\n\\midrule\nStandard & \\cell{"
            + value
            + "}{0.4} \\\\\nCoT & \\cell{14.3}{0.4} \\\\\n\\end{tabular}"
        )
        text = "\\documentclass{article}\n\\newcommand{\\cell}[2]{#1$_{\\pm #2}$}\n\\begin{document}\n" + body + "\n\\end{document}\n"
        (folder / "main.tex").write_text(text, encoding="utf-8")
        return folder

    a, b = load(paper(tmp_path / "a", "6.5"), "a"), load(paper(tmp_path / "b", "6.9"), "b")
    assert [c.value for c in a.tables[0].rows[1]] == [None, 6.5]
    (t,) = compare(a, b).tables
    assert [(c.row, c.old, c.new) for c in t.cells] == [("Standard", "6.5_\\pm 0.4", "6.9_\\pm 0.4")]


def test_a_row_whose_name_changed_a_little_is_still_compared(tmp_path: Path) -> None:
    """From ALBERT v1 -> v6: the row "ALBERT | xlarge | 59M" became "... | 60M" and its results changed; and from LoRA
    v1 -> v2: cells written ".32" (no leading zero) are numbers."""
    from arxiv_diff.paper import load

    def paper(folder: Path, params: str, squad: str, met: str) -> Path:
        folder.mkdir()
        rows = f"ALBERT & base & 12M & 89.3 & .45 \\\\\n & xlarge & {params} & {squad} & {met} \\\\\n"
        text = "\\documentclass{article}\\begin{document}\n\\begin{tabular}{lllll}\nModel & Size & Params & SQuAD & MET \\\\\n\\midrule\n"
        (folder / "main.tex").write_text(text + rows + "\\end{tabular}\n\\end{document}\n", encoding="utf-8")
        return folder

    (t,) = compare(load(paper(tmp_path / "a", "59M", "93.0", ".32"), "a"), load(paper(tmp_path / "b", "60M", "92.5", ".30"), "b")).tables
    assert t.rows_renamed == [("ALBERT | xlarge | 59M", "ALBERT | xlarge | 60M")] and not t.rows_added
    assert [(c.column, c.old, c.new, c.kind) for c in t.cells] == [("SQuAD", "93.0", "92.5", "value"), ("MET", ".32", ".30", "value")]


def test_authors_as_real_papers_write_them(tmp_path: Path) -> None:
    """From the measurement: names separated by ~~~~~~~ (Longformer) or the paper's own spacing command (MAE),
    footnote marks (Transformer), a list wrapped onto a second line (DINO, LoRA), affiliations after the names."""
    from arxiv_diff.paper import load

    author = r"""\newcommand{\authorskip}{\hspace{2.5mm}}
\author{
Iz Beltagy\Thanks{\enspace Equal contribution.}
~~~~~~~~~Matthew E. Peters\textcolor{blue}{\footnotemark[1]} \authorskip Kaiming He$^{*,\dagger}$\\
Julien Mairal$^{2}$~~~~~~~\textbf{Yuanzhi Li}\\[2mm]
\small $^{*}$equal technical contribution \\
Allen Institute for Artificial Intelligence, Seattle, WA, USA\\
{\tt $\{$beltagy$\}$@allenai.org}}"""
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "main.tex").write_text(
        "\\documentclass{article}\n" + author + "\n\\begin{document}\n\\maketitle\nText here.\n\\end{document}\n", encoding="utf-8"
    )
    assert load(tmp_path / "p", "p").authors == ["Iz Beltagy", "Matthew E. Peters", "Kaiming He", "Julien Mairal", "Yuanzhi Li"]
