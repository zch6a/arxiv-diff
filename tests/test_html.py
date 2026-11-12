from __future__ import annotations

import re
from pathlib import Path

from helpers import version, write

from arxiv_diff.cli import main
from arxiv_diff.diff import compare
from arxiv_diff.html import page


def test_page_shows_the_changes_side_by_side(tmp_path: Path) -> None:
    d = compare(version(tmp_path, "v1"), version(tmp_path, "v2", BIG="28.9", ABSTRACT="We propose a new architecture. It reaches 28.4 BLEU."))
    html = page([(d, "a paper")])
    assert html.startswith("<!doctype html>") and "<title>a paper</title>" in html
    assert '<td class="n">28.4</td><td class="n">28.9</td>' in html and "+0.5 better" in html
    # the number that changed in a sentence: struck on the left, marked on the right, the row flagged
    assert '<div class="pair numbers">' in html and "<del>28.4</del>" in html and "<ins>28.9</ins>" in html
    assert '<h2 id="d0-abstract">Abstract</h2>' in html and "<del>based on attention</del>" in html
    assert '<a href="#d0-tables">tables</a>' in html


def test_paper_text_cannot_inject_anything(tmp_path: Path) -> None:
    hostile = r'Click <script>alert(1)</script> <img src=x onerror=alert(2)> "quoted" & more.'
    d = compare(version(tmp_path, "v1"), version(tmp_path, "v2", ABSTRACT=hostile, TITLE="</title><script>x</script>"))
    html = page([(d, "<b>about</b>")])
    assert "<script>alert" not in html and "<img" not in html and "<b>about" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "&lt;img src=x onerror=alert(2)&gt;" in html
    assert html.count("<script>") == 1  # the page's own
    # nothing is loaded from anywhere
    assert "Content-Security-Policy" in html and "default-src 'none'" in html
    assert not re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", html)


def test_html_from_the_command_line(tmp_path: Path) -> None:
    a, b = write(tmp_path / "old"), write(tmp_path / "new", BIG="28.9")
    out = tmp_path / "diff.html"
    assert main([str(a), str(b), "--format", "html", "-o", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "<del>28.4</del>" in html and html.rstrip().endswith("</html>")


def test_several_steps_on_one_page(tmp_path: Path) -> None:
    v1, v2, v3 = version(tmp_path, "v1"), version(tmp_path, "v2", BIG="28.9"), version(tmp_path, "v3", BIG="29.1")
    html = page([(compare(v1, v2), ""), (compare(v2, v3), "")])
    assert '<a href="#d0">v1 → v2</a>' in html and '<a href="#d1">v2 → v3</a>' in html
    assert '<section id="d1">' in html and "<ins>29.1</ins>" in html
