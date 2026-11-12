"""Synthetic papers for the tests: every version is written by the test itself (no real paper is used)."""

from __future__ import annotations

from pathlib import Path

from arxiv_diff.paper import Paper, load

TABLE = r"""\begin{table}[t]
\caption{BLEU scores on newstest2014.}\label{tab:main}
\begin{tabular}{lcc}
\toprule
Model & EN-DE & EN-FR \\
\midrule
ByteNet & 23.75 & -- \\
GNMT + RL & 24.6 & 39.92 \\
%ROWS%
Transformer (big) & \textbf{%BIG%} & \textbf{41.0} \\
\bottomrule
\end{tabular}
\end{table}
"""

PAPER = r"""\documentclass{article}
\title{%TITLE%}
\author{Ada Lovelace\thanks{Equal contribution.} \\ Analytical Engines Ltd \\ \texttt{ada@example.org} \And %AUTHOR2% \\ Example University}
\begin{document}
\maketitle
\begin{abstract}
%ABSTRACT%
\end{abstract}
\input{sections/intro}
\section{%METHOD%}
We stack six identical layers. Each layer has two sub-layers.
\begin{equation}
  \mathrm{Attention}(Q, K, V) = \mathrm{softmax}(QK^T / \sqrt{d_k}) V \label{eq:att}
\end{equation}
%TABLE%
\section{Results}
On the WMT 2014 English-to-German task, the big model reaches %BIG% BLEU. Training took 3.5 days on 8 GPUs.
%EXTRA%
\begin{figure}[t]
\centering
\includegraphics[width=\linewidth]{figures/%FIG%.pdf}
\caption{%CAPTION%}\label{fig:model}
\end{figure}
\section{Conclusion}
We presented a model based on attention alone.
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
"""

INTRO = r"""\section{Introduction}
Recurrent models process tokens one at a time~\cite{hochreiter1997}. This makes them slow to train.

Attention lets a model relate distant positions~\cite{%CITE%}.
"""

BIB = r"""@article{hochreiter1997, title={Long Short-Term Memory}, author={Hochreiter, Sepp and Schmidhuber, J{\"u}rgen},
  journal={Neural Computation}, year={1997}}
@article{bahdanau2014, title={Neural Machine Translation by Jointly Learning to Align and Translate}, author={Bahdanau, Dzmitry},
  journal={%VENUE%}, year={%YEAR%}}
@article{luong2015, title={Effective Approaches to Attention-based Neural Machine Translation}, author={Luong, Minh-Thang},
  journal={EMNLP}, year={2015}}
"""

V1 = {
    "TITLE": "Attention Is All You Need",
    "AUTHOR2": "Charles Babbage",
    "ABSTRACT": "We propose a new architecture based on attention. It reaches 28.4 BLEU on English-to-German.",
    "METHOD": "Model",
    "BIG": "28.4",
    "ROWS": "",
    "EXTRA": "",
    "FIG": "model",
    "CAPTION": "The model architecture.",
    "CITE": "bahdanau2014",
    "VENUE": "arXiv preprint arXiv:1409.0473",
    "YEAR": "2014",
}


def write(folder: Path, **changes: str) -> Path:
    """A synthetic paper in `folder`: version 1, with `changes` to its placeholders."""
    v = {**V1, **changes}
    text = PAPER.replace("%TABLE%", TABLE)
    intro, bib = INTRO, BIB
    for k, val in v.items():
        text, intro, bib = (s.replace(f"%{k}%", val) for s in (text, intro, bib))
    (folder / "sections").mkdir(parents=True, exist_ok=True)
    (folder / "main.tex").write_text(text, encoding="utf-8")
    (folder / "sections" / "intro.tex").write_text(intro, encoding="utf-8")
    (folder / "refs.bib").write_text(bib, encoding="utf-8")
    return folder


def version(tmp: Path, name: str, **changes: str) -> Paper:
    return load(write(tmp / name, **changes), name)
