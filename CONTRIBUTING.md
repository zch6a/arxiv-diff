# Contributing

The most useful contributions are **real cases it got wrong**: an issue with the arXiv id and versions, what
arxiv-diff reported, and what really changed (a table paired with the wrong one, a changed number it missed, a
sentence reported as rewritten that was not).

## Development

```bash
uv sync
uv run pytest -q          # no test reaches the network: the papers are written by the tests, arXiv is a fake
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

A fix comes with a test built from the real case that motivated it (a few lines of LaTeX in two versions, written by
the test). To measure on real papers:

```bash
uv run python scripts/measure_versions.py ids.txt /tmp/arxiv-diff-sources --max 20
```

It fetches v1 and the latest version of each paper (one request every 3 seconds) into a folder outside this
repository, compares them, and audits the tables independently of the report. Delete the folder afterwards; never
commit papers' sources.

## Where things are

| | |
|---|---|
| `latex.py` | the document in reading order, LaTeX as text, sentences, sections, title, authors, figures |
| `paper.py` | one version of a paper |
| `diff.py` | the comparison: sections, sentences, tables, figures, authors, references |
| `arxiv.py` | versions and sources from arXiv |
| `report.py`, `html.py` | the terminal and Markdown reports; the side-by-side page |
| `cli.py` | the command line (and the JSON report) |
