"""One version of a paper, read from its LaTeX source: what the diff compares."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from paper_proof.bib import _matching
from paper_proof.check import Reference
from paper_proof.latex import find_main, read_project
from paper_proof.tables import Table, find_tables

from . import latex
from .latex import Figure, Section, Sentence, Source


@dataclass
class Paper:
    label: str  # how the reports name this version: "v2", or the folder
    main: str  # the main .tex file, relative to the folder
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: list[Sentence] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)  # the cited ones (every entry after \nocite{*})
    cited: list[str] = field(default_factory=list)  # keys, in the order the text first cites them
    source: Source = field(default_factory=lambda: Source(""))

    @property
    def words(self) -> int:
        """Words of prose (abstract and sections; not tables, figures or references)."""
        return sum(len(s.text.split()) for sec in self.sections for s in sec.sentences) + sum(len(s.text.split()) for s in self.abstract)


FRONT_MATTER = re.compile(
    r"\\(?:title|author|icmlauthor|icmltitle|affiliation|institute|address|email|keywords|date|thanks|icmlaffiliation"
    r"|icmlcorrespondingauthor|icmlkeywords)\s*(?:\[[^\]]*\])?\s*\{"
)


class NoSource(ValueError):
    """A folder with no LaTeX document in it."""


def load(folder: Path, label: str = "") -> Paper:
    """Read the LaTeX project in `folder` (its main file found the way paper-proof finds it)."""
    main = find_main(folder) if folder.is_dir() else folder if folder.suffix == ".tex" else None
    if main is None:
        raise NoSource(f"{folder}: no LaTeX document (a .tex file with \\documentclass and \\begin{{document}})")
    project = read_project(main)
    src = latex.expand(project)
    base = folder.resolve() if folder.is_dir() else main.resolve().parent
    paper = Paper(label or folder.name, main.resolve().relative_to(base).as_posix(), source=src)
    paper.title = latex.title(src)
    paper.authors = latex.authors(src)
    a, b = latex.abstract(src)
    paper.abstract = latex.sentences(src, a, b) if b > a else []
    # the front of the document (before the first heading) without its title, authors and abstract
    skip = [(a, b)] if b > a else []
    for m in FRONT_MATTER.finditer(src.text):
        end = _matching(src.text, m.end(), "{", "}")
        if end > 0:
            skip.append((m.start(), end + 1))
    for m in re.finditer(r"\\begin\{(abstract\*?|icmlauthorlist|IEEEkeywords|keywords|CCSXML|teaserfigure)\}.*?\\end\{\1\}", src.text, re.S):
        skip.append((m.start(), m.end()))
    paper.sections = latex.sections(src, skip)
    for file, text in project.texts.items():
        paper.tables += find_tables(latex.expand_macros(text, src.macros), file)  # \cell{6.5}{0.4} is a number
    for table in paper.tables:  # names and headers as the paper prints them (its macros, \multirow, \rule)
        table.caption = re.sub(r"\\label\S*\s*", "", table.caption).strip()
        for row in table.rows:
            for cell in row:
                if cell.value is None and cell.raw:
                    cell.text = latex.detex(cell.raw, src.macros)
                    bare = re.fullmatch(r"([-−]?)\.(\d+)\s*%?", cell.text)  # .32: a number without its leading zero
                    if bare:
                        cell.value, cell.decimals = float(f"{bare.group(1).replace('−', '-')}0.{bare.group(2)}"), len(bare.group(2))
    paper.figures = latex.figures(src)
    paper.references = project.checked()
    paper.cited = list(project.cited)
    return paper
