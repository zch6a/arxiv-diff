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
| 4 | ALBERT: the row "xlarge, 59M" became "xlarge, 60M": its 5 changed results unseen | rows named alike paired as renamed, their cells compared |
| 4 | LoRA: `.32` cells not numbers | numbers without a leading zero |
| 5 | LoRA: columns `Accuracy (%)` → `Acc. (%)`: 4 changed results unseen | columns paired as renamed too |
| 5 | authors: LoRA's list wrapped over two lines (a false "removed"), footnote marks, affiliations as names, 4 papers with none found | authors read per group until the first affiliation; middle initials ignored when comparing |
| 6 | LoRA: v1's one Adapter row paired with the wrong one of v2's two (3 false changes) | between rows named alike, the one with the old row's numbers |

Final run: 131 table results changed, 69 checked by hand in the sources (all real); 30 numbers changed in the text,
all real edits; 0 unexplained numbers in 389 audited table pairs; authors right in all 40 versions (3 real changes).
The sources are deleted.

Tests: 44, Python 3.10 and 3.14; ruff, mypy clean.

### 2026-11-13 — on GitHub

- Public repository https://github.com/zch6a/arxiv-diff (topics: arxiv, latex, diff, research, papers,
  reproducibility, github-actions). Before pushing: every commit by zch6a with the noreply address, no attribution
  lines, no personal paths, no paper sources in the tree (38 files).
- CI green on the first run: tests on Ubuntu, Windows and macOS with Python 3.10 and 3.13, ruff, mypy; the Action job
  on the example's two versions found `TinyFormer · EN-XX: 31.2 → 30.8` as the check expects.

Next: five polishing rounds, then v0.1.0.

## Polishing round 1 (2026-11-13)

1. **Function**: every README command run as a user would (two folders, two `.tex` files, the same folder twice, one
   folder, three sources, a missing path, `--all` with folders, `--fail-on`, the four formats, `-o` into a new
   folder, `v0`). Found: `-o` into a folder that does not exist crashed with a traceback; usage errors exited 1 (the
   code `--fail-on` uses) in some places and 2 in others; `--all` with two folders was silently ignored; a version
   arXiv does not have was only found out by downloading. All fixed: usage errors exit 2 with argparse's message,
   `--all` is for one arXiv id, the versions are checked against arXiv's record before anything is downloaded,
   `-o` creates its folder; the exit codes are in both READMEs.
2. **Code**: an independent review (an agent reading the code without my notes) found nine bugs, eight reproduced;
   each is now a test in `tests/test_review.py`:
   - **renamed-column pairing joined different columns** (EN-DE and EN-RO share a word, so the EN-DE results were
     reported as changed EN-RO results; same for Acc@1 → Acc@5): a column now counts as renamed only if most of its
     numbers stayed, or, with no numbers to go by, its header is nearly the same;
   - **ties went to the last** table, figure and section (an unchanged table was reported added when a second table
     with its caption followed it): ties now go to the first;
   - **author changes were invisible for non-Latin names** (Cyrillic, Greek, CJK compared as empty strings);
   - **the Action built the old version wrongly**: with `path` naming the main `.tex` only that file was archived
     (no `\input` files, no `.bib`); `base: main` was fetched but not usable by name; with no base in a shallow clone
     `HEAD~1` did not exist. Now: the main file's whole folder, the fetched commit itself, a deepened clone for the
     commit before; a base starting with `-` is refused. CI runs the Action with a `.tex` path;
   - **hostile sources could make it hang**: `\input` fanning out (4^12 copies), a command expanding into itself,
     a 1.5 MB paragraph (quadratic sentence splitting: 23 s), thousands of unclosed `\(` or environments. While
     testing the fixes two more quadratic spots showed: finding a sentence's line counted newlines from the top of
     the file each time (25 s for 90,000 sentences), and matching long runs of identical sentences. Now: each file
     `\input` at most 8 times within a 50 MB budget, self-referencing commands left alone and expansion capped,
     environments found with one search each, sentence splitting in one pass, a line index per file, matching with
     the same beginning and end set aside. Every hostile case now takes about a second;
   - the JSON report lost the arXiv title (the diff's own `title` overwrote it): now `arxiv_title`;
   - `--all` threw every step away when one version was PDF-only: the others are reported, the failed step named;
   - `<summary>` lines in the Markdown report would show `\~1`, `\_` on GitHub (Markdown is not read inside HTML);
   - an empty "Sections" heading when only tables changed; a missing `\input` file's name read as a sentence.
3. **Tests**: 47 → 63; Python 3.10 and 3.14 locally, Ubuntu/Windows/macOS with 3.10 and 3.13 in CI.
4. **Experience**: an 81,600-word paper compares in 2.8 s; error messages say what to do.
5. **Docs**: exit codes in both READMEs; CONTRIBUTING describes the GitHub render check.
6. **Engineering**: one dependency (paper-proof, which brings pypdf); CI green with the Action's new check.
7. **Security and privacy**: the Markdown report checked as GitHub renders it (`scripts/check_github_render.py`):
   hostile text in a synthetic paper's title, abstract, a sentence, a caption and a table row renders as text only.
   That check found a list placed right under the table being read as more table rows, and caption changes and
   renamed rows and columns missing from the Markdown report; both fixed.

## Polishing round 2 (2026-11-13)

1. **Function: 16 more real papers.** The rest of paper-proof's 50 (2207.12598 to 2312.00752): 16 with several
   versions (Mamba's v1 is PDF-only, reported as such). 156 table changes, 8 numbers in the text; the independent
   audit: 0 unexplained numbers in 200 table pairs. By hand: MT-Bench (GPT-4 Writing 62.9% → 61.2%), LLaVA-1.5
   (MME 502.8 → 809.6, the right row though keyed by position) are real. Found:
   - **BLIP-2 relabelled a table's columns** ("val, test-dev" became "test-dev, test-std", same numbers): the column
     headed "test-dev" did change from 76.04 to 75.84, but the reader must know the numbers only moved. Now: old
     columns whose numbers stand under another header are named, "numbers now under another header: val →
     test-dev; test-dev → test-std (headers corrected? the changes above may be relabelling)";
   - authors separated by escaped spaces (`\ \ \ \ \ `, the diffusion survey) read as one six-word name; names set
     in `\texttt` (ControlNet v1) dropped with the e-mail addresses `\texttt` usually holds. Both fixed.
   The sources are deleted.
2. **Code: a second independent review** (the reports, the HTML page, the docs against the behaviour). Fixed, each
   with a test in `tests/test_review2.py`:
   - `--fail-on results` and the headline missed results: a table result replaced by text (`41.0` → `--`), and a
     number changed in a sentence where another was added beside it (`28.4` → `28.9 (std 0.2)`);
   - sections that only swapped places reported "no changes" (and `--fail-on any` passed);
   - "better"/"worse" from words that are not metrics (a caption's "is" read as Inception Score: `Layers: 6 → 12
     (+6, better)`); a changed spread (`4.1 ± 0.2 → 4.1 ± 0.5`) counted as a changed result. Now captions give a
     direction only by an arrow, "higher/lower is better" or an unambiguous metric; spreads are cell changes;
   - figure file names and source paths sent to the terminal without making control characters visible;
   - Markdown: every numbers-only line (`- # ...`) was a heading; no list of the numbers changed in the text; rows
     added only counted, not named; conclusions cut at 30 without saying so;
   - an unexpected error exited 1, which reads as "results changed": now 2; a one-version paper gave no JSON; the
     JSON was an object or a list depending on how many steps: `--all` is always a list;
   - HTML: the numbers filter hid caption diffs and left empty sections; no "Numbers in the text"; "1 sentences";
     the fold link said "unfold all" over open sections; moved-only sections missing; one title for several steps;
     the CSP allowed any inline script: now only the page's own, by its hash (checked in Chrome);
   - the terminal cut captions at 70 characters (an edit after that showed no change): now a word diff;
   - the headline said nothing about rows added or removed in tables; renamed lists cut at 12 without a marker;
     `--full` did not show added or removed sections' sentences;
   - the Action and SECURITY said the tool runs "at the action's own ref", but paper-proof came from a movable tag:
     now pinned by commit;
   - docs: the JSON's "file and line on both sides" (only sentences have them; cells have the new line), `--full`
     and `--keep`, the Skill's report order, the Chinese sample, the demo image's description, `.bst`, and two
     places still saying macros with arguments are compared as written.
3. **Tests**: 63 → 78; a backslash inside an f-string expression (valid on 3.12+, a syntax error on 3.10) was caught
   by ruff before the commit.
4. **Experience**: the HTML page's navigation reaches every part; the terminal's caption changes are readable.
5. **Docs**: as above; both READMEs say the same.
6. **Engineering**: CI green; the one dependency pinned by commit.
7. **Security and privacy**: the CSP by hash; control characters in every name the paper controls.

## Polishing round 3 (2026-11-13)

1. **Function: 20 papers outside machine learning**, picked from arXiv's API (the newest-updated papers with a v2
   or later in hep-th, math.AP, cond-mat.str-el, astro-ph.GA, q-bio.NC, quant-ph, math.CO, econ.EM,
   physics.flu-dyn, stat.ME; one is PDF-only). Tables: 0 unexplained numbers in 69 audited pairs. But "numbers in
   the text" were mostly formulas: 47 reported, about a dozen real. Fixed, each a test in `tests/test_fields.py`:
   - numbers inside inline math and displayed equations (`\frac12` → `\frac{1}{2}`, exponents, coefficients) are
     not numbers in the text; a number written in math mode (`$28.4$ BLEU`) still is; the formula's change still
     shows in the sentence's word diff;
   - references are one token, written `‹label›` (`\eqref{G8}` → `\eqref{G12}` is not a changed number); DOIs are
     one token (a Zenodo record);
   - Elsevier's marks after a name (`\corref{cor1}` made "Piyush Akimitsucor"); names compared by first initial and
     surname ("E. Elmakies" in v1 is "Elad Elmakies" in v6);
   - a version whose authors are typed into the page without `\author` (econ.EM v2): the authors are said to be
     unread there, not removed; its `\iflatexml` branch (the text arXiv's HTML version gets) is no longer read
     beside the PDF's, which had doubled its title block.
   After the fixes: 16 numbers in the text, all real prose edits (84 → 85 percent, 1.68 → 1.66, a confidence bound
   0.33 → 0.32, an insert renamed S2 → S2.5, a range 880 → 1300). The sources are deleted.
2. **Code**: the changes above are small and local; no dead code left (an unused variable caught in review).
3. **Tests**: 78 → 88; Python 3.10 and 3.14 locally, three systems in CI.
4. **Experience**: installed from GitHub as the README says (`uvx --from git+https://github.com/zch6a/arxiv-diff`):
   15 s the first time, three packages, the right report.
5. **Docs**: the README's sample of *Attention Is All You Need* no longer matched the tool's summary line (table
   rows added are now counted): re-fetched, the sample and the demo image regenerated; `‹labels›` in the READMEs,
   the Skill and the HTML page's footer.
6. **Engineering**: CI green.
7. **Security and privacy**: the arXiv queries carry a generic User-Agent; the sources were kept in the scratchpad
   only while measuring.

## Polishing round 4 (2026-11-13)

1. **Function**: nothing new promised; every earlier test still holds after the restructuring (90 tests).
2. **Code**:
   - `diff.py` had grown to 991 lines holding three jobs. Split by moving whole top-level definitions (by their
     syntax-tree spans, no code retyped): `words.py` (tokens, word diffs, numbers in sentences, similarity, pairing;
     213 lines), `tables.py` (the table comparison; 343 lines), `diff.py` (the paper level; 467 lines), which
     re-exports the public names so nothing that imports from it changed.
   - Types: section, table and figure statuses, sentence and cell kinds are `Literal` types (mypy now rejects a
     misspelled one; it found two places that passed a plain string); the last two `type: ignore` removed (an
     `object` parameter, an unchecked regex match).
3. **Tests**: 88 → 90, among them a speed test for a fully rewritten section.
4. **Experience: speed.** A synthetic worst case (100 sections of 60 sentences, every sentence rewritten, 1,500
   changed cells) took 43.5 s to compare: in a fully rewritten section every old sentence was compared with every
   new one (3,600 comparisons a section), each re-tokenizing both sentences and rebuilding the matcher's index.
   Now each sentence is tokenized once, each new sentence indexed once, a sentence is compared with those near its
   own place (a rewrite keeps its order; the band widens with the difference in length), and pairs whose cheap upper
   bound is below the pairing threshold are skipped (exact: they would not be taken). 12 s for that case; the HTML
   page for it (3.7 MB) is made in 0.3 s. A real paper of 81,600 words compares in under 3 s.
5. **Docs**: CONTRIBUTING's map of the modules.
6. **Engineering**: CI green. A commit went in with a lint warning in a test (fixed in the next commit); commits
   are now made only when ruff passes.
7. **Security and privacy**: no new inputs or outputs this round.

## Polishing round 5 (2026-11-13) — before 0.1.0

1. **Function: a final independent review** (correctness, release readiness, a new user's path, docs). Fixed, each
   a test in `tests/test_final.py`:
   - **high**: a paper declaring `\newif\iflatexml` lost all its prose (the declaration was read as a branch that
     never closed, and everything after it was blanked), as did `\iff` inside such a branch. Now declarations are
     skipped, `\iff` is not a conditional, and a branch without its `\fi` blanks nothing;
   - the release workflow failed to move `v0` on a plain (lightweight) tag: it now reads the tag's type;
   - sentence pairing missed pairs when sentences were removed at one end of a long section and added at the other
     (0 of 15 found): candidates now come from the sentences' distinctive words as well as from their place;
   - "Yu Zhang" and "Yang Zhang" were one person (first initial and surname): an initial now only matches a first
     name that starts with it; "Mila Nikolova" and "Yale Song" were taken for institutions;
   - `\$500 ... \$300` read as a formula; results in math mode (`$3\times$`, `$\mathbf{91.2}$`) were left out;
     the placeholder for a formula showed as `⟨math⟩` in the context words: now `[formula]`;
   - `#` (only numbers changed) on sentences whose change was inside a formula, with no number to show;
   - a one-version paper gave `[]` without `--all`, where every other run gives an object;
   - captions with both arrows, or with FID and IS, gave a direction to every column;
   - a folder above the paper's silently picked a main file: the report now names it;
   - README: commands with arguments are expanded too (it still said argument-less), what "numbers in the text"
     leave out, the exit status with `--all`.
   Checked and fine: the release workflow's version check and CHANGELOG extraction; the wheel (the ten modules, the
   licence, the entry point, the metadata, paper-proof pinned by commit).
2. **Code**: the version is said once (a test compares `__version__`, `pyproject.toml` and the CHANGELOG).
3. **Tests**: 90 → 101; Python 3.10 caught a `tomllib` import in a test (3.11+), replaced.
4. **Experience**: `--help` explains the formats and colours and gives the exit status.
5. **Docs**: the CHANGELOG's 0.1.0 section written in full; the README's measurement covers all 55 papers.
6. **Engineering**: CI green; the social preview left out of the source archive.
7. **Security and privacy**: unchanged; no network access in the tests, none in the review.

## Released: 0.1.0 (2026-11-13)

https://github.com/zch6a/arxiv-diff/releases/tag/v0.1.0 — the release workflow built and tested the tag (version
and CHANGELOG checked), made the release with the wheel and the source archive, and moved `v0` to the release
commit, so `uses: zch6a/arxiv-diff@v0` works. Not published to PyPI (and cannot be as it stands: its dependency,
paper-proof, is a git reference).

### 2026-11-14 — Chinese README: AI tone

- 2 places: a 3-item 顿号 list used as the subject of a sentence turned into clauses (who needs to know which numbers changed), and a semicolon between two independent sentences split into a full stop (how LaTeX is read).
- The checks follow the findings of lieflat-less-ai-tone (shiujan, CC BY-NC 4.0); its findings applied, its text not copied.
- Left as they are: the feature enumeration in the opening (it must be complete), the field and paper lists in parentheses, the semicolon list of problems found by measuring, colon-led lists, tables.
### 2026-11-14 — a link to research-kit

Both READMEs now end (before the licence) with a short section pointing to research-kit, the toolkit's front door: all
thirteen tools in the order of the work, and one Claude Code plugin marketplace for their skills. Documentation only.

### 2026-11-14 — 0.2.0: arxiv-diff watch

Chosen from research-kit's list of needs nothing covers: "hear when a paper you follow or cite posts a new version,
and what changed in it" (arxiv-sanity-lite and zotero-arxiv-daily track new submissions only).

`watch.py`: arXiv ids from a `.bib` (eprint fields, links, `arXiv:` notes, `10.48550/arXiv.` DOIs; the version an
entry names, the keys citing it), the latest versions from arXiv's API (Atom; error entries skipped), a JSON state
file, `--since` refined with the OAI version list, `--diff` through the existing compare and headline. 9 tests with a
fake arXiv (API, OAI and sources): every input kind, first run, a new version with its diff, newly published, dry run,
`--since` picking v2 of four, a 429 answered on the second try, broken state file.

Measured on the bibliographies of two of the 50 papers (fetched to a temporary folder, deleted after): Mamba's 75
arXiv references, 1 new version since 2025-06-01; LoRA's 44, 2 since 2023-01-01, and their diffs ("GPT Understands,
Too" rewritten, 89%; two numbers changed in "Backward Feature Correction"). The first try was refused with HTTP 429
(arXiv had been asked for 50 sources minutes before): retrying after a wait was added.
