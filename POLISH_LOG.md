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

### 2026-11-13 — the side-by-side page

- `--format html`: one self-contained file (no fonts, scripts or images from anywhere; a Content-Security-Policy
  of `default-src 'none'`, no referrer), light and dark. Tables first (row, column, old, new, change, better/worse;
  cleared cells grouped; the caption as a word diff), title and authors, the abstract side by side, then every
  changed section folded with its counts (`+added −removed ~changed · unchanged`), the conclusion and short diffs
  unfolded; each pair shows the old sentence with deletions struck on the left, the new one with insertions marked on
  the right, and the file:line of each. Filters: only sentences whose numbers changed; hide moved sentences;
  unfold all. `--all` puts every step on one page with links between them.
- Every piece of the paper's text is escaped: a test writes `<script>` and `<img onerror>` into a paper's abstract
  and title and checks that the page shows them as text, with its own script the only one.
- Found by looking at the rendered page of *Attention Is All You Need* v1 → v7: the word diff lost the spaces
  around inserted words ("encoder**and a**decoder"). Runs now keep the spaces before their words, kept text is
  spaced as the new version spaces it, and the highlight starts after the space (terminal, Markdown and HTML).

Tests: 33, Python 3.10 and 3.14; ruff, mypy clean.

### 2026-11-13 — the GitHub Action, the docs, and measuring on 20 real papers

- **The Action** (`action.yml`): the paper in a pull request against its base commit (or any ref, or a folder);
  the Markdown report in the job summary, JSON and Markdown files as outputs; `fail-on: results` to fail when a
  number changed. CI runs it on the example's two versions and checks what it finds. Also: release workflow, Skill
  and plugin, READMEs (English, Chinese), SECURITY, CONTRIBUTING, CHANGELOG, demo image, social preview.
- **The measurement** (`scripts/measure_versions.py`): v1 against the latest version of the 20 papers with several
  versions among paper-proof's 50 (sources fetched at one request every 3 seconds into the scratchpad, deleted
  afterwards). Besides the report it audits every pair of tables independently: each number that left a table or
  arrived in it must be explained by a reported change. Seven runs; each found something, fixed with a test from the
  real case:

| run | found | fix |
|---|---|---|
| 1 | Swin: `Swin-L (HTC++)` and `Swin-L (HTC++)*` read as one row: 4 false changes | names keep their marks; duplicates numbered after normalising |
| 1 | ALBERT: `89.3/82.1 → 89.3/82.3` missed (only a cell's first number was compared) | every number in a cell compared; formatting (`±0.2` vs `\textsubscript\pm.2`) is not a change |
| 1 | GPT-3: a table whose every row was renamed ("Completion" → "Target Completion") unpaired | pairing by file, shape and columns |
| 2 | text: years in citation keys, `12288 → 12,288`, `$4.6$k → 4,600`, `WikiText-103` as minus 103 (11 false) | citations one token; values compared with k/M/B; no minus after a letter |
| 2 | Chain-of-Thought: cells `\cell{6.5}{0.4}` not numbers | the paper's commands with arguments expanded before tables are read |
| 4 | ALBERT: the row `xlarge | 59M` became `| 60M`: its 5 changed results unseen | rows named alike paired as renamed, their cells compared |
| 4 | LoRA: `.32` cells not numbers | numbers without a leading zero |
| 5 | LoRA: columns `Accuracy (%)` → `Acc. (%)`: 4 changed results unseen | columns paired as renamed too |
| 5 | authors: LoRA's list wrapped over two lines (a false "removed"), footnote marks, affiliations as names, 4 papers with none found | authors read per group until the first affiliation; middle initials ignored when comparing |
| 6 | LoRA: v1's one Adapter row paired with the wrong one of v2's two (3 false changes) | between rows named alike, the one with the old row's numbers |

Final run: 131 table results changed, 69 checked by hand in the sources (all real); 30 numbers changed in the text,
all real edits; 0 unexplained numbers in 389 audited table pairs; authors right in all 40 versions (3 real changes).
The sources are deleted.

Tests: 44, Python 3.10 and 3.14; ruff, mypy clean.
