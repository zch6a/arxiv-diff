---
name: arxiv-diff
description: Compare two versions of a paper with arxiv-diff. Reports which result numbers changed in its tables (by row and column) and in its text, the sentences added, removed and rewritten, and changes to the abstract, conclusion, authors, figures and cited references. Works on any two arXiv versions (fetched from arXiv) or two LaTeX folders. Use when the user asks what changed between versions of a paper (v1 vs v2, preprint vs camera-ready), whether a paper's results changed after review, or to review the changes to a LaTeX paper in a branch or pull request.
license: MIT
compatibility: Needs Python 3.10+ and uv. Runs arxiv-diff with uvx from GitHub (git+https://github.com/zch6a/arxiv-diff) unless an arxiv-diff command is installed. For arXiv ids it fetches the sources from arxiv.org (one request every 3 seconds, into a temporary folder that is deleted); for folders it reads them offline.
metadata:
  homepage: https://github.com/zch6a/arxiv-diff
---

# Comparing versions of a paper with arxiv-diff

```bash
uvx --from git+https://github.com/zch6a/arxiv-diff arxiv-diff 1706.03762          # v1 against the latest version
uvx --from git+https://github.com/zch6a/arxiv-diff arxiv-diff 1706.03762v3        # v2 against v3
uvx --from git+https://github.com/zch6a/arxiv-diff arxiv-diff old/ new/           # two LaTeX folders
```

Use `arxiv-diff` instead of the `uvx ...` prefix if it is installed. Useful options:

- `--all`: every version against the next (v1 → v2 → … → latest).
- `--format html -o diff.html`: one self-contained page with the two versions side by side; tell the user where it
  is. `--format json` for everything, with file and line; `--format markdown` for a comment.
- `--full`: every changed sentence (the terminal report shows a few per section otherwise).

For a paper in a git repository, put the old version in a folder first (`git worktree add /tmp/old <ref>`, or
`git archive <ref> -- paper | tar -x -C /tmp/old`) and compare the two folders.

## Reading the report

- **Tables** come first: each changed result as row · column: old → new, with the difference and, when the column's
  metric says which way is better, "better" or "worse". These are what readers most need to know about; say them
  first, with the table's label.
- **Numbers in the text**: numbers that changed inside sentences (the abstract's claims especially).
- Then the title and authors, the abstract and conclusion, sections (renamed, added, removed, moved; `#` marks a
  sentence where only numbers changed), figures (the image files and captions), and references (added, removed, or
  now cited as the published version).

Sentences are compared as plain text (formatting dropped, citations as `[keys]`, references as `‹labels›`), so a
change in formatting alone is not reported. Image contents are not compared, only which files a figure shows.
When a reported change matters to the user's question, quote it with its file and line rather than paraphrasing.
