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
    assert ("-", "28.4") in c.words and ("+", "28.9") in c.words
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
    assert d.abstract[0].words[-2:] == [("+", "alone"), ("=", ".")]


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
    assert ("+", "Transformer") in f.caption
    assert [r.key for r in d.references.added] == ["luong2015"]
    (u,) = d.references.updated
    assert u.key == "bahdanau2014" and "now the published version" in u.what and "year 2014 -> 2015" in u.what
