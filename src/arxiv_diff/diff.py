r"""What changed between two versions of a paper.

Sections are paired by title, then by their text (a renamed or moved section is still the same section); within a
pair, sentences are paired the same way and each changed sentence gets a word-level diff, with the numbers that
changed in it picked out. Tables are paired by \label, caption or shape, and their cells by row name and column
header, so a result that changed is reported as "Transformer (big), EN-DE: 28.4 → 28.9", wherever the row moved.
Figures, authors and cited references are compared on their own.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from paper_proof.check import Reference

from .latex import Figure, Section, Sentence
from .paper import Paper
from .tables import CellChange, TableDiff, caption_direction, cell_numbers, columns, diff_table, diff_tables, match_tables, rows
from .words import NumberChange, Status, Where, _numbers_only, _pair, _words, number_changes, opcodes, similarity, tokens, word_diff

# what the reports, the scripts and the tests use from here (the comparison's parts live in words.py and tables.py)
__all__ = [
    "AuthorDiff", "CellChange", "Change", "Diff", "FigureDiff", "NumberChange", "RefChange", "RefDiff", "SectionDiff", "Summary",
    "TableDiff", "Where", "align_sections", "caption_direction", "cell_numbers", "columns", "compare", "diff_authors", "diff_figures",
    "diff_references", "diff_sections", "diff_sentences", "diff_table", "diff_tables", "match_tables", "number_changes", "opcodes",
    "rows", "similarity", "tokens", "word_diff",
]  # fmt: skip


# ---------------------------------------------------------------- sentences


@dataclass
class Change:
    kind: Literal["added", "removed", "changed", "moved"]  # moved: the same sentence, now in another section
    old: Sentence | None = None
    new: Sentence | None = None
    words: list[tuple[str, str]] = field(default_factory=list)
    numbers: list[NumberChange] = field(default_factory=list)
    numbers_only: bool = False  # nothing but numbers changed in the sentence
    other: str = ""  # for a moved sentence: the section it moved from or to


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def diff_sentences(a: list[Sentence], b: list[Sentence]) -> list[Change]:
    """The sentences added, removed and changed between two lists of sentences, in reading order."""
    ka, kb = [_key(s.text) for s in a], [_key(s.text) for s in b]
    out: list[Change] = []
    for op, i1, i2, j1, j2 in opcodes(ka, kb):
        if op == "equal":
            continue
        pairs = _pair(ka[i1:i2], kb[j1:j2], 0.5)
        i, j = i1, j1
        for pi, pj in [*pairs, (i2 - i1, j2 - j1)]:
            out += [Change("removed", old=a[k]) for k in range(i, i1 + pi)]
            out += [Change("added", new=b[k]) for k in range(j, j1 + pj)]
            if i1 + pi < i2:
                x, y = a[i1 + pi], b[j1 + pj]
                numbers = number_changes(x.text, y.text) if x.kind == y.kind == "text" else []  # a displayed equation is a formula
                out.append(Change("changed", x, y, word_diff(x.text, y.text), numbers, _numbers_only(x.text, y.text)))
            i, j = i1 + pi + 1, j1 + pj + 1
    return out


# ---------------------------------------------------------------- sections


@dataclass
class SectionDiff:
    status: Status
    old: Where | None
    new: Where | None
    level: int
    changes: list[Change] = field(default_factory=list)
    renamed: bool = False
    moved: bool = False  # it is now somewhere else in the paper's order
    appendix: bool = False
    sentences: tuple[int, int] = (0, 0)  # how many the section has in each version

    @property
    def unchanged(self) -> int:
        """Sentences the same in both versions."""
        return max(0, self.sentences[1] - sum(c.kind in ("added", "changed") or (c.kind == "moved" and c.new is not None) for c in self.changes))

    @property
    def name(self) -> str:
        w = self.new or self.old
        return w.name if w and w.name else "(before the first section)"


def _title_key(s: Section) -> str:
    if not s.title and s.level == 0 and not s.number:
        return "\0front"
    return " ".join(_words(s.title))


def _text_of(s: Section) -> str:
    return " ".join(t.text for t in s.sentences)


def align_sections(a: list[Section], b: list[Section]) -> list[tuple[Section | None, Section | None, bool]]:
    """Pairs (old, new, moved) of the two versions' sections in the new version's order, a removed section where it
    used to be. Equal titles pair first (in order); then, among the rest, similar titles or similar text."""
    ka, kb = [_title_key(s) for s in a], [_title_key(s) for s in b]
    match: dict[int, int] = {}
    for blk in SequenceMatcher(None, ka, kb, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            match[blk.a + k] = blk.b + k
    # in the gaps between pairs: by title or by text, in order
    ordered = sorted(match.items())
    bounds = [(-1, -1), *ordered, (len(a), len(b))]
    for (pa, pb), (qa, qb) in zip(bounds, bounds[1:], strict=False):
        ia, ib = list(range(pa + 1, qa)), list(range(pb + 1, qb))
        if not ia or not ib:
            continue
        texts_a = [ka[i] + " " + _text_of(a[i]) for i in ia]
        texts_b = [kb[j] + " " + _text_of(b[j]) for j in ib]
        for x, y in _pair(texts_a, texts_b, 0.4):
            match[ia[x]] = ib[y]
    # what is left: moved sections (the same title, or most of the same text, elsewhere)
    moved: set[int] = set()
    left_b = [j for j in range(len(b)) if j not in match.values()]
    for i in range(len(a)):
        if i in match or not left_b:
            continue
        scored = [(1.0 if ka[i] == kb[j] and ka[i] else similarity(_text_of(a[i]), _text_of(b[j])), j) for j in left_b]
        score, j = max(scored, key=lambda c: (c[0], -c[1]))  # on a tie, the first
        if score >= 0.6 and (ka[i] == kb[j] or len(_text_of(a[i]).split()) >= 20):
            match[i] = j
            moved.add(i)
            left_b.remove(j)
    inverse = {j: i for i, j in match.items()}
    out: list[tuple[Section | None, Section | None, bool]] = []
    placed_old: set[int] = set()

    def removed_up_to(limit: int) -> None:
        for i in range(limit):
            if i not in match and i not in placed_old:
                out.append((a[i], None, False))
                placed_old.add(i)

    for j, s in enumerate(b):
        oi = inverse.get(j)
        if oi is not None and oi not in moved:
            removed_up_to(oi)
        out.append((a[oi] if oi is not None else None, s, oi in moved))
        if oi is not None:
            placed_old.add(oi)
    removed_up_to(len(a))
    return out


def _where(s: Section) -> Where:
    return Where(s.name, s.file, s.line)


def diff_sections(a: list[Section], b: list[Section]) -> list[SectionDiff]:
    out = []
    for old, new, moved in align_sections(a, b):
        if old is None and new is not None:
            out.append(
                SectionDiff(
                    "added",
                    None,
                    _where(new),
                    new.level,
                    [Change("added", new=t) for t in new.sentences],
                    appendix=new.appendix,
                    sentences=(0, len(new.sentences)),
                )
            )
        elif new is None and old is not None:
            out.append(
                SectionDiff(
                    "removed",
                    _where(old),
                    None,
                    old.level,
                    [Change("removed", old=t) for t in old.sentences],
                    appendix=old.appendix,
                    sentences=(len(old.sentences), 0),
                )
            )
        elif old is not None and new is not None:
            changes = diff_sentences(old.sentences, new.sentences)
            renamed = _title_key(old) != _title_key(new)
            status: Status = "changed" if changes or renamed else "same"
            sentences = (len(old.sentences), len(new.sentences))
            out.append(SectionDiff(status, _where(old), _where(new), new.level, changes, renamed, moved, new.appendix, sentences))
    # a sentence removed in one place and added, word for word, in another has moved
    removed: dict[str, list[tuple[Change, SectionDiff]]] = {}
    for sd in out:
        for c in sd.changes:
            if c.kind == "removed" and c.old is not None:
                removed.setdefault(_key(c.old.text), []).append((c, sd))
    for sd in out:
        for c in sd.changes:
            if c.kind == "added" and c.new is not None and removed.get(_key(c.new.text)):
                r, rsd = removed[_key(c.new.text)].pop(0)
                if rsd is sd:
                    continue
                r.kind, c.kind = "moved", "moved"
                r.other, c.other = sd.name, rsd.name
    for sd in out:
        if sd.status == "same" and any(c.kind != "moved" for c in sd.changes):
            sd.status = "changed"
    return out


# ---------------------------------------------------------------- figures, authors, references


@dataclass
class FigureDiff:
    status: Status
    name: str
    old: Where | None
    new: Where | None
    graphics: tuple[list[str], list[str]] | None = None  # (old, new) when the files shown changed
    caption: list[tuple[str, str]] = field(default_factory=list)  # a word diff, when the caption changed


def diff_figures(a: list[Figure], b: list[Figure]) -> list[FigureDiff]:
    used_b: set[int] = set()
    match: dict[int, int] = {}
    for i, f in enumerate(a):
        if f.label:
            j = next((j for j, g in enumerate(b) if j not in used_b and g.label == f.label), None)
            if j is not None:
                match[i] = j
                used_b.add(j)
    for i, f in enumerate(a):
        if i in match:
            continue
        cands = [
            (len(set(f.graphics) & set(g.graphics)) + similarity(f.caption, g.caption), j)
            for j, g in enumerate(b)
            if j not in used_b and (set(f.graphics) & set(g.graphics) or similarity(f.caption, g.caption) >= 0.6)
        ]
        if cands:
            j = max(cands, key=lambda c: (c[0], -c[1]))[1]  # on a tie, the first
            match[i] = j
            used_b.add(j)
    inverse = {j: i for i, j in match.items()}
    out = []
    for j, g in enumerate(b):
        w = Where(g.name, g.file, g.line)
        if j not in inverse:
            out.append(FigureDiff("added", g.name, None, w))
            continue
        f = a[inverse[j]]
        d = FigureDiff("same", g.name, Where(f.name, f.file, f.line), w)
        if f.graphics != g.graphics:
            d.graphics = (f.graphics, g.graphics)
        if _key(f.caption) != _key(g.caption):
            d.caption = word_diff(f.caption, g.caption)
        if d.graphics or d.caption:
            d.status = "changed"
        out.append(d)
    for i, f in enumerate(a):
        if i not in match:
            out.append(FigureDiff("removed", f.name, Where(f.name, f.file, f.line), None))
    return out


def _person(name: str) -> str:
    """A name compared without accents, case, middle names or initials: by its first initial and surname, so "Ed H.
    Chi" is "Ed Chi" and "E. Elmakies" is "Elad Elmakies".

    >>> _person("Ed H. Chi") == _person("Ed Chi"), _person("E. Elmakies") == _person("Elad Elmakies"), _person("Björn Ommer")
    (True, True, 'b ommer')
    """
    s = unicodedata.normalize("NFKD", name)
    words = re.findall(r"[^\W\d_]+", "".join(c for c in s if not unicodedata.combining(c)).lower())  # any script
    return f"{words[0][0]} {words[-1]}" if len(words) >= 2 else " ".join(words)


@dataclass
class AuthorDiff:
    old: list[str]
    new: list[str]
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    reordered: bool = False
    unread: str = ""  # "old" or "new": that version names no authors the way they are read (\\author and the like)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.reordered)


def diff_authors(a: list[str], b: list[str]) -> AuthorDiff:
    if bool(a) != bool(b):  # names typed into the page without \\author, in one version: not a change of authors
        return AuthorDiff(a, b, unread="new" if a else "old")
    ka, kb = [_person(n) for n in a], [_person(n) for n in b]
    d = AuthorDiff(a, b, [n for n, k in zip(b, kb, strict=True) if k not in ka], [n for n, k in zip(a, ka, strict=True) if k not in kb])
    common_a = [k for k in ka if k in kb]
    common_b = [k for k in kb if k in ka]
    d.reordered = common_a != common_b
    return d


@dataclass
class RefChange:
    key: str
    title: str
    what: str = ""  # for an updated reference: what changed in it


@dataclass
class RefDiff:
    added: list[RefChange] = field(default_factory=list)  # cited now, not before
    removed: list[RefChange] = field(default_factory=list)
    updated: list[RefChange] = field(default_factory=list)  # still cited, its entry changed (a preprint now published...)
    rekeyed: int = 0  # the same work under a new key


def _title(r: Reference) -> str:
    return " ".join(_words(r.title))


def _is_preprint(r: Reference) -> bool:
    return bool(r.arxiv or re.search(r"arxiv|corr\b|preprint|biorxiv|medrxiv|openreview", r.venue + " " + r.doi, re.I))


def diff_references(a: list[Reference], b: list[Reference]) -> RefDiff:
    d = RefDiff()
    by_key_a = {r.key: r for r in a}
    by_key_b = {r.key: r for r in b}
    by_title_a = {_title(r): r for r in a if _title(r)}
    by_title_b = {_title(r): r for r in b if _title(r)}
    pairs: list[tuple[Reference, Reference]] = []
    for r in b:
        old = by_key_a.get(r.key)
        if old is None and _title(r) in by_title_a and by_title_a[_title(r)].key not in by_key_b:
            old = by_title_a[_title(r)]
            d.rekeyed += 1
        if old is None:
            d.added.append(RefChange(r.key, r.title))
        else:
            pairs.append((old, r))
    for r in a:
        if r.key not in by_key_b and not (_title(r) and _title(r) in by_title_b and by_title_b[_title(r)].key not in by_key_a):
            d.removed.append(RefChange(r.key, r.title))
    for old, new in pairs:
        what = []
        if _title(old) and _title(new) and _title(old) != _title(new):
            what.append(f'title "{old.title}" → "{new.title}"')
        if _is_preprint(old) and not _is_preprint(new) and (new.venue or new.doi):
            what.append(f"now the published version ({new.venue or new.doi})")
        elif old.venue and new.venue and " ".join(_words(old.venue)) != " ".join(_words(new.venue)):
            what.append(f'venue "{old.venue}" → "{new.venue}"')
        if old.year and new.year and old.year != new.year:
            what.append(f"year {old.year} → {new.year}")
        if what:
            d.updated.append(RefChange(new.key, new.title, "; ".join(what)))
    return d


# ---------------------------------------------------------------- the whole paper


@dataclass
class Summary:
    words_old: int = 0
    words_new: int = 0
    changed_share: float = 0.0  # share of the old prose's words removed or rewritten
    sentences_added: int = 0
    sentences_removed: int = 0
    sentences_changed: int = 0
    sentences_moved: int = 0
    text_numbers_changed: int = 0
    sections_added: int = 0
    sections_removed: int = 0
    sections_renamed: int = 0
    table_values_changed: int = 0  # changed results: see CellChange.result
    table_rows_added: int = 0
    table_rows_removed: int = 0
    tables_added: int = 0
    tables_removed: int = 0
    figures_added: int = 0
    figures_removed: int = 0
    figures_changed: int = 0
    references_added: int = 0
    references_removed: int = 0
    references_updated: int = 0
    authors_added: int = 0
    authors_removed: int = 0


@dataclass
class Diff:
    old: str  # the versions' labels
    new: str
    title: tuple[str, str] | None
    authors: AuthorDiff
    abstract: list[Change]
    sections: list[SectionDiff]
    tables: list[TableDiff]
    figures: list[FigureDiff]
    references: RefDiff
    summary: Summary

    @property
    def changed(self) -> bool:
        s = self.summary
        return bool(
            self.title or self.authors.changed or self.abstract or any(sd.status != "same" or sd.moved for sd in self.sections)
            or any(t.status != "same" for t in self.tables) or any(f.status != "same" for f in self.figures)
            or s.references_added or s.references_removed or s.references_updated
        )  # fmt: skip


def compare(a: Paper, b: Paper) -> Diff:
    sections = diff_sections(a.sections, b.sections)
    tables = diff_tables(a.tables, b.tables)
    d = Diff(
        a.label,
        b.label,
        (a.title, b.title) if _key(a.title) != _key(b.title) else None,
        diff_authors(a.authors, b.authors),
        diff_sentences(a.abstract, b.abstract),
        sections,
        tables,
        diff_figures(a.figures, b.figures),
        diff_references(a.references, b.references),
        Summary(a.words, b.words),
    )
    s = d.summary
    removed_words = 0
    for c in [*d.abstract, *(c for sd in sections for c in sd.changes)]:
        if c.kind == "added":
            s.sentences_added += 1
        elif c.kind == "removed":
            s.sentences_removed += 1
            removed_words += len(c.old.text.split()) if c.old else 0
        elif c.kind == "moved":
            s.sentences_moved += 1
        else:
            s.sentences_changed += 1
            s.text_numbers_changed += len(c.numbers)
            removed_words += sum(len(t.split()) for op, t in c.words if op == "-")
    s.sentences_moved //= 2  # each moved sentence is counted where it left and where it arrived
    s.changed_share = round(removed_words / a.words, 4) if a.words else 0.0
    s.sections_added = sum(sd.status == "added" for sd in sections)
    s.sections_removed = sum(sd.status == "removed" for sd in sections)
    s.sections_renamed = sum(sd.renamed for sd in sections)
    s.table_values_changed = sum(c.result for t in tables for c in t.cells)
    s.table_rows_added = sum(len(t.rows_added) for t in tables if t.status == "changed")
    s.table_rows_removed = sum(len(t.rows_removed) for t in tables if t.status == "changed")
    s.tables_added = sum(t.status == "added" for t in tables)
    s.tables_removed = sum(t.status == "removed" for t in tables)
    s.figures_added = sum(f.status == "added" for f in d.figures)
    s.figures_removed = sum(f.status == "removed" for f in d.figures)
    s.figures_changed = sum(f.status == "changed" for f in d.figures)
    s.references_added = len(d.references.added)
    s.references_removed = len(d.references.removed)
    s.references_updated = len(d.references.updated)
    s.authors_added = len(d.authors.added)
    s.authors_removed = len(d.authors.removed)
    return d
