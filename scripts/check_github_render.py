"""The Markdown report rendered by GitHub itself (gh api markdown, GFM): text from a hostile paper (links, autolinked
addresses, images, HTML, mentions, table pipes) makes nothing but text. Needs gh, signed in. The paper is synthetic;
only its report is sent. Writes report.md and report.html into OUT_DIR.

    uv run python scripts/check_github_render.py OUT_DIR
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from arxiv_diff.diff import compare
from arxiv_diff.paper import load
from arxiv_diff.report import markdown

HOSTILE = r"See https://evil.example and www.evil.example [click](https://x.example) <img src=x onerror=alert(1)> @octocat **bold** `code` | pipe"


def paper(folder: Path, extra: str) -> Path:
    """Names stay the same, so the hostile text lands in every part of the report: a changed sentence (folded in a
    section's details), a table's caption and a new row, the abstract, the title."""
    folder.mkdir(parents=True)
    row = f"Baseline {extra.replace('|', '').replace('&', '')} & 0.5 \\\\\n" if extra else ""
    table = (
        f"\\begin{{table}}\\caption{{Scores {extra}}}\\label{{tab:main}}\\begin{{tabular}}{{lc}}\nModel & Score \\\\\n\\midrule\n"
        f"{row}Ours & {'2' if extra else '1'}.0 \\\\\n\\end{{tabular}}\\end{{table}}"
    )
    sentence = "The proposed model works well on every benchmark we tried, including the hardest ones"
    text = (
        f"\\documentclass{{article}}\\title{{A {extra} title}}\\author{{Ada Lovelace \\and Grace Hopper}}\\begin{{document}}\n"
        f"\\begin{{abstract}}We study things. {extra}\\end{{abstract}}\n\\section{{Results}}\n{sentence} {extra}.\n{table}\n\\end{{document}}\n"
    )
    (folder / "main.tex").write_text(text, encoding="utf-8")
    return folder


out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp())
d = compare(load(paper(tmp / "a", ""), "v1"), load(paper(tmp / "b", HOSTILE), "v2"))
md = markdown(d, HOSTILE)
(out / "report.md").write_text(md, encoding="utf-8")
html = subprocess.run(
    ["gh", "api", "markdown", "-f", f"text={md}", "-f", "mode=gfm"], capture_output=True, text=True, encoding="utf-8", check=True
).stdout
(out / "report.html").write_text(html, encoding="utf-8")
problems = []
if re.search(r"<a\s[^>]*href=\"https?://(?:evil|x)\.example", html):
    problems.append("a link to the hostile address")
if re.search(r"<img\b", html):
    problems.append("an image")
if "user-mention" in html or 'href="https://github.com/octocat"' in html:
    problems.append("a mention")
if "<strong>bold</strong>" in html:
    problems.append("the paper's own bold")
print("rendered:", len(html), "bytes; tables:", html.count("<table"), "; details:", html.count("<details"))
print("PROBLEMS: " + "; ".join(problems) if problems else "nothing from the paper renders")
sys.exit(1 if problems else 0)
