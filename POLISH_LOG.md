# arxiv-diff — development and polishing log

## Development

### 2026-11-13 — the core, the arXiv fetch, the reports

- **Reading one version** (`latex.py`, `paper.py`): paper-proof reads the project (comments, `\iffalse`, `\input`,
  the bibliography); the document is put back together in reading order, with every position mapped to its file
  and line. Title, authors (any template: `\author` with `\and`/`\And`/`\\`, `\icmlauthor`, IEEE blocks; affiliations,
  e-mails and footnotes left out), abstract, numbered sections (appendix lettered), figures (graphics, caption,
  label), tables (paper-proof), cited references.
- **Prose as text** (`detex`): the document's own argument-less macros expanded (`\newcommand{\dff}{d_{ff}}`),
  citations as `[keys]`, references as `(labels)`, inline math kept as written, accents applied, floats left out,
  displayed equations as units of their own. Sentences split outside braces and math, not after abbreviations.
- **The diff** (`diff.py`): sections paired by title, then by text (renamed and moved sections stay paired);
  sentences paired within a section (most similar, in order), each changed one with a word diff and the numbers that
  changed in it; a sentence that left one section word for word and arrived in another is "moved", not removed and
  added. Tables paired by `\label`, caption, then rows and columns; cells by row name (a `\multirow` name filled down)
  and column header (spanning headers filled across); value, text and bold-only changes; better/worse from the
  column's (or caption's) metric. Figures by label, graphics, caption. Authors added/removed/reordered. References by
  key (re-keyed ones by title), and "now the published version" when a preprint entry became a venue.
- **arXiv** (`arxiv.py`): versions and dates from OAI-PMH (arXivRaw), sources from `/e-print/<id>v<n>`, one request
  every 3 seconds, unpacked by paper-proof's safe extraction into a temporary folder that is deleted afterwards
  (`--keep DIR` keeps it). A PDF-only version is an error. The tests inject a fake arXiv; none reaches the network.
- **Reports**: terminal (tables first, then numbers in the text, title and authors, abstract, conclusion, sections,
  figures, references; `--full` for every sentence), Markdown (nothing from the paper renders; sections folded; cut
  before GitHub's comment limit), JSON (everything, with deltas). `--all` compares every version with the next;
  `--fail-on results|any` for CI.

**Checked on a real paper** — *Attention Is All You Need*, v1 (2017-06-12) → v7 (2023-08-02), each reported change
checked by hand in the two sources:

| reported | in the sources |
|---|---|
| Transformer (big) · BLEU EN-FR 41.0 → 41.8 (table and abstract) | yes, the known correction |
| base · d_ff 1024 → 2048 (Table 3) | yes: v1's table said 1024 |
| params cells emptied in rows (A) and (D) (8 cells, were 65) | yes: v7 leaves them blank |
| row (E) "positional embedding instead of sinusoids" added | yes |
| a Luong et al. (2015) multi-task row added to the parsing table | yes |
| 4 references added (he2016deep, multiseq2seq, press2016using, sukhbaatar2015) | yes |
| the attention-dropout paragraph removed from 5.4 | yes |
| figure: graphics ModalNet-32 → ModalNet-20 | yes |

What the first run got wrong, fixed before the commit: user macros left unexpanded (a `$\dff$` header read as
"column 4"), `\rule{0pt}{2.0ex}` and `\multirow` left in row names, `\begin{center}` read as the word "center", a
footnote with math in it cut short, and a guess that hid cells cleared under a `\multirow` (they were real edits;
cleared and filled cells are now grouped per column instead).

Tests: 29 (synthetic papers written by the tests; a fake arXiv), Python 3.10 and 3.14; ruff, mypy clean.

Next: the side-by-side HTML page; measurement on more multi-version papers (recall of number changes); Action,
Skill, READMEs, CI, release.
