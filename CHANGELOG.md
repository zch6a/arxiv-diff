# Changelog

## 0.1.0

The first release.

- Compares two versions of a paper: any two arXiv versions (fetched from arXiv, paced, into a temporary folder), two
  LaTeX folders, or, in the GitHub Action, the paper in a pull request against its base.
- Tables: paired by label, caption, rows and columns; changed values by row and column, with the difference and
  better/worse; cleared and filled cells; the bold marker moving; rows and columns added and removed.
- Text: sections paired by title and text (renamed and moved sections), sentences paired with word diffs, numbers
  that changed in sentences, moved sentences; abstract and conclusion on their own.
- Title, authors, figures (image files, captions), cited references (added, removed, preprint → published).
- Reports: terminal, Markdown, JSON, and a self-contained side-by-side HTML page.
