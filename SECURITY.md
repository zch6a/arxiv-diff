# Security

arxiv-diff reads LaTeX sources that may come from anyone (any paper on arXiv, a co-author's branch).

## What it does

- **Sends nothing about you.** For an arXiv id it asks arXiv for the paper's record and sources, with a generic
  User-Agent and nothing else; one request every 3 seconds, as arXiv asks. For folders it does not touch the network.
- **Keeps nothing.** Sources are unpacked into a temporary folder deleted when the comparison is done (unless you
  pass `--keep DIR`). Only `.tex`, `.bib`, `.bbl`, `.sty`, `.cls` and `.bst` files are unpacked, only inside that folder
  (no absolute paths, no `..`, no links), and an archive that unpacks to more than 500 MB is refused (paper-proof's
  extraction).
- **Runs nothing from the paper.** The LaTeX is read as text; `\input` is followed only inside the project folder.
  It never runs LaTeX or anything in the project.
- **Hostile text stays text.** The terminal report shows control characters as visible escapes; the Markdown report
  renders no links, images, HTML or mentions from the paper; the HTML page escapes every piece of the paper's text
  and its Content-Security-Policy (`default-src 'none'`) stops it from loading anything at all.
- **The GitHub Action** needs only `contents: read`, runs the tool at the action's own ref, and passes inputs through
  environment variables.

## What it does not protect against

- **Changes it cannot see.** It compares the LaTeX: a result changed only inside an image, or in a PDF-only version,
  is not reported. Text produced by macros with arguments is compared as written.

## Reporting a vulnerability

Please open a private security advisory on GitHub (Security → Report a vulnerability) rather than a public issue.
