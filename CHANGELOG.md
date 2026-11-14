# Changelog

## 0.2.0 — 2026-11-14

**`arxiv-diff watch`**: which of the arXiv papers you cite posted a new version, and what changed in it.

- Reads a `.bib`, a LaTeX folder (its `.bib` files), a text file of ids, or ids; finds arXiv papers by `eprint`,
  arxiv.org links, `arXiv:` in any field and arXiv DOIs, with the entries that cite each.
- Remembers the versions seen in a JSON file next to the input (`--state`); a `.bib` entry that names a version is
  compared with it from the first run. Reports new versions and papers that now have a journal reference.
- `--since DATE` (compared with the version current on that date, from arXiv's version list), `--diff` (arxiv-diff's
  headline for each new version), `--format text|markdown|json`, `--dry-run`, `--fail-on-new`.
- arXiv's API in batches of 100 ids, paced; a 429 or 503 answer is retried after 15, 60 and 180 seconds.
- The README has a weekly GitHub workflow that opens an issue.

## 0.1.0

The first release: what changed between two versions of a paper, results first.

- **What it compares**: any two arXiv versions of a paper (fetched from arXiv, one request every three seconds,
  into a temporary folder that is deleted), every version against the next (`--all`), two LaTeX folders or main
  `.tex` files, or, in the GitHub Action, the paper in a pull request against its base commit.
- **Tables**: paired by label, caption, rows and columns (a table whose rows were all renamed is still paired);
  cells by row name and column header, so a row that moved is the same row; rows and columns whose names changed a
  little are paired as renamed (by name and by the numbers they hold); changed results with their difference, and
  "better" or "worse" when the column's metric, an arrow or the caption says which way is better; every number of a
  cell compared ("89.3/82.1"); a result replaced by text; cleared and filled cells grouped; the bold marker moving;
  rows and columns added and removed; caption changes as word diffs; numbers that now stand under another header
  pointed out (headers corrected).
- **Text**: sections paired by title and text (renamed, added, removed, moved); sentences paired within each
  section, each changed one as a word diff; the numbers that changed in sentences listed (not those inside formulas,
  citation keys, reference labels or DOIs, and not the same number written another way); a sentence moved to
  another section is "moved"; the abstract and conclusion on their own.
- **Front matter, figures, references**: title; authors added, removed or reordered (any template's way of listing
  them; compared by first initial and surname); figures by label, image files and caption; cited references added,
  removed, re-keyed, or now cited as the published version.
- **Reading LaTeX**: `\input` followed, comments, `\iffalse` and `\iflatexml` branches dropped, the paper's own
  commands expanded (with arguments too), citations as `[keys]`, references as `‹labels›`, inline math as written.
- **Reports**: terminal (results first; `--full` for every sentence), Markdown for pull requests (nothing from the
  paper renders; sections folded; cut before GitHub's comment limit), JSON, and a self-contained side-by-side HTML
  page (no outside resources, its own script allowed by hash, filters for sentences whose numbers changed).
- **Exit status**: 0 compared, 1 when `--fail-on results` or `any` says so, 2 when it could not compare.
- **Robust on hostile sources**: no runaway `\input`, commands, sentences or environments; control characters in
  anything from the paper shown, not sent to the terminal.
- **Measured** on 55 real papers with several arXiv versions (machine learning, physics, mathematics, astronomy,
  neuroscience, economics, statistics), with an audit of every pair of tables independent of the report; see the
  README and `POLISH_LOG.md`.
