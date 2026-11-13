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
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from paper_proof.check import Reference
from paper_proof.tables import HIGHER, LOWER, Table, direction

from .latex import Figure, Section, Sentence
from .paper import Paper

# ---------------------------------------------------------------- words and numbers

# a URL; a citation's keys, whole ([huang2019evaluating] is not the year 2019); a number (a minus sign only where
# a sign can be: not the hyphen of WikiText-103); a command; a word; a mark
TOKEN = re.compile(
    r"\s*(?:https?://[^\s)\]]+[^\s)\].,;:]|\[(?=[^\]]*[A-Za-z])[^\[\]]{1,300}\]|(?:(?<![\w)])[-−])?\d+(?:[.,]\d+)*"
    r"|\\[A-Za-z]+|[^\W\d_]+|\w+|[^\w\s])"
)
NUMBER = re.compile(r"[-−]?\d+(?:[.,]\d+)*")
SCALE = {"k": 1e3, "K": 1e3, "M": 1e6, "B": 1e9}


def _value(toks: list[str], k: int) -> float:
    """The number at toks[k], with a k/M/B written right after it (42k is 42,000)."""
    v = float(toks[k].strip().replace("−", "-").replace(",", ""))
    after = toks[k + 1 : k + 3]
    if after and after[0] == "$":  # $4.6$k
        after = after[1:]
    nxt = after[0] if after else ""
    return v * SCALE.get(nxt, 1.0) if nxt and not nxt[0].isspace() else v


def opcodes(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    """SequenceMatcher's opcodes for two lists, the same beginning and end set aside first (most of two versions of
    a paper), and a long remainder matched with its popular items ignored: hundreds of identical items (a hostile or
    generated source) would otherwise take quadratic time.

    >>> opcodes(list("abcxdef"), list("abcydef"))
    [('equal', 0, 3, 0, 3), ('replace', 3, 4, 3, 4), ('equal', 4, 7, 4, 7)]
    """
    n, limit = 0, min(len(a), len(b))
    while n < limit and a[n] == b[n]:
        n += 1
    m = 0
    while m < limit - n and a[len(a) - 1 - m] == b[len(b) - 1 - m]:
        m += 1
    ops: list[tuple[str, int, int, int, int]] = [("equal", 0, n, 0, n)] if n else []
    mid_a, mid_b = a[n : len(a) - m], b[n : len(b) - m]
    if mid_a or mid_b:
        sm = SequenceMatcher(None, mid_a, mid_b, autojunk=max(len(mid_a), len(mid_b)) > 2000)
        ops += [(op, i1 + n, i2 + n, j1 + n, j2 + n) for op, i1, i2, j1, j2 in sm.get_opcodes()]
    if m:
        ops.append(("equal", len(a) - m, len(a), len(b) - m, len(b)))
    return ops


def tokens(s: str) -> list[str]:
    """Words, numbers and marks, each with the spaces before it (so joining them gives the text back, but for
    trailing spaces).

    >>> tokens("BLEU of 28.4, up 1,000x.")
    ['BLEU', ' of', ' 28.4', ',', ' up', ' 1,000', 'x', '.']
    """
    return TOKEN.findall(s)


def word_diff(a: str, b: str) -> list[tuple[str, str]]:
    """The two texts as runs of ("=", kept), ("-", removed) and ("+", added) text. Each run keeps the spaces before
    its words, so the "=" and "+" runs joined are the new text, and kept text is as the new version spaces it.

    >>> word_diff("It reaches 28.4 BLEU.", "It now reaches 28.9 BLEU.")
    [('=', 'It'), ('+', ' now'), ('=', ' reaches'), ('-', ' 28.4'), ('+', ' 28.9'), ('=', ' BLEU.')]
    >>> "".join(t for op, t in word_diff("an encoder-decoder configuration.", "an encoder and a decoder.") if op != "-")
    'an encoder and a decoder.'
    """
    ta, tb = tokens(a), tokens(b)
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in opcodes([t.strip() for t in ta], [t.strip() for t in tb]):
        if op == "equal":
            out.append(("=", "".join(tb[j1:j2])))
            continue
        if i2 > i1:
            out.append(("-", "".join(ta[i1:i2])))
        if j2 > j1:
            out.append(("+", "".join(tb[j1:j2])))
    return out


@dataclass
class NumberChange:
    old: str
    new: str
    before: str  # the words before it, in the new text
    after: str


def number_changes(a: str, b: str) -> list[NumberChange]:
    """The numbers that changed between two versions of a sentence, each with the words around it.

    >>> old, new = "BLEU of 28.4 on EN-DE and 41.0 on EN-FR.", "BLEU of 28.9 on EN-DE and 41.0 on EN-FR."
    >>> [(n.old, n.new, n.before, n.after) for n in number_changes(old, new)]
    [('28.4', '28.9', 'BLEU of', 'on EN-DE')]
    >>> number_changes("as high as 12288 [smith2019]", "as high as 12,288 [smith2020]"), number_changes("of 42k examples", "of 42,000 examples")
    ([], [])
    """
    ta, tb = tokens(a), tokens(b)
    sa, sb = [t.strip() for t in ta], [t.strip() for t in tb]
    out = []
    for op, i1, i2, j1, j2 in opcodes(sa, sb):
        if op != "replace":
            continue
        na = [(i1 + k, t) for k, t in enumerate(sa[i1:i2]) if NUMBER.fullmatch(t)]
        nb = [(j1 + k, t) for k, t in enumerate(sb[j1:j2]) if NUMBER.fullmatch(t)]
        if not na or not nb:
            continue
        for (i, x), (j, y) in zip(na, nb, strict=False):  # in order; one added beside them is left out
            if x != y and _value(sa, i) != _value(sb, j):  # 12288 and 12,288 are the same number
                before = "".join(tb[max(0, j - 4) : j]).strip()
                after = "".join(tb[j + 1 : j + 5]).strip()
                out.append(NumberChange(x, y, before, after))
    return out


def _numbers_only(a: str, b: str) -> bool:
    """Whether the two sentences differ in their numbers and nothing else."""
    sa, sb = [t.strip() for t in tokens(a)], [t.strip() for t in tokens(b)]
    ops = [o for o in opcodes(sa, sb) if o[0] != "equal"]
    return bool(ops) and all(o[0] == "replace" and all(NUMBER.fullmatch(t) or t == "%" for t in sa[o[1] : o[2]] + sb[o[3] : o[4]]) for o in ops)


def _words(s: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)*|\w+", s.lower())


def similarity(a: str, b: str) -> float:
    """How much of two texts is the same, by words in order (0 to 1); quick and approximate for long texts.

    >>> round(similarity("the model reaches 28.4 BLEU", "the model now reaches 28.9 BLEU"), 2)
    0.73
    """
    wa, wb = _words(a), _words(b)
    if not wa and not wb:
        return 1.0
    sm = SequenceMatcher(None, wa, wb, autojunk=False)
    if sm.real_quick_ratio() < 0.3 or sm.quick_ratio() < 0.3:
        return sm.quick_ratio()
    return sm.ratio() if len(wa) * len(wb) < 250_000 else sm.quick_ratio()


def _pair(a: list[str], b: list[str], threshold: float, bonus: Callable[[int, int], float] | None = None) -> list[tuple[int, int]]:
    """Pairs (i, j) of similar texts, in order on both sides, with the largest total similarity."""
    n, m = len(a), len(b)
    if not n or not m:
        return []
    if n * m > 4000:  # a long run of changed text: pair greedily
        out, j0 = [], 0
        for i, x in enumerate(a):
            top = max(((similarity(x, b[j]), j) for j in range(j0, min(m, j0 + 30))), default=(0.0, -1))
            if top[0] >= threshold:
                out.append((i, top[1]))
                j0 = top[1] + 1
        return out
    sim = [[similarity(x, y) for y in b] for x in a]
    if bonus is not None:  # among texts alike enough, prefer the pair the bonus favours
        sim = [[v + bonus(i, j) if v >= threshold else v for j, v in enumerate(row)] for i, row in enumerate(sim)]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            take = sim[i][j] + best[i + 1][j + 1] if sim[i][j] >= threshold else 0.0
            best[i][j] = max(best[i + 1][j], best[i][j + 1], take)
    out, i, j = [], 0, 0
    while i < n and j < m:
        if sim[i][j] >= threshold and abs(best[i][j] - (sim[i][j] + best[i + 1][j + 1])) < 1e-12:
            out.append((i, j))
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return out


# ---------------------------------------------------------------- sentences


@dataclass
class Change:
    kind: str  # "added", "removed", "changed", or "moved" (the same sentence, now in another section)
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
                out.append(Change("changed", x, y, word_diff(x.text, y.text), number_changes(x.text, y.text), _numbers_only(x.text, y.text)))
            i, j = i1 + pi + 1, j1 + pj + 1
    return out


# ---------------------------------------------------------------- sections


@dataclass
class Where:
    name: str
    file: str
    line: int


@dataclass
class SectionDiff:
    status: str  # "same", "changed", "added", "removed"
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
            status = "changed" if changes or renamed else "same"
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


# ---------------------------------------------------------------- tables


@dataclass
class CellChange:
    row: str
    column: str
    old: str  # the cell as text
    new: str
    old_value: float | None
    new_value: float | None
    kind: str  # "value" (a number changed), "text" (a cell changed otherwise), "bold" (only the bold marking)
    old_bold: bool = False
    new_bold: bool = False
    line: int = 0  # in the new version
    better: bool | None = None  # by which way the column is better, when that is known

    @property
    def delta(self) -> float | None:
        if self.old_value is None or self.new_value is None:
            return None
        return round(self.new_value - self.old_value, 10)

    @property
    def result(self) -> bool:
        """A changed result: a number that changed, or a result replaced by text or text by a result ("41.0" -> "--");
        not a cell cleared or filled in, a spread, or the bold marking."""
        if self.kind == "value":
            return True
        has_a, has_b = bool(cell_numbers(self.old)), bool(cell_numbers(self.new))
        return self.kind == "text" and bool(self.old.strip() and self.new.strip()) and has_a != has_b


@dataclass
class TableDiff:
    status: str  # "same", "changed", "added", "removed"
    name: str  # \label, else the caption's beginning
    old: Where | None
    new: Where | None
    caption: tuple[str, str] | None = None  # (old, new) when the caption changed
    cells: list[CellChange] = field(default_factory=list)
    rows_added: list[str] = field(default_factory=list)
    rows_removed: list[str] = field(default_factory=list)
    columns_added: list[str] = field(default_factory=list)
    columns_removed: list[str] = field(default_factory=list)
    rows_renamed: list[tuple[str, str]] = field(default_factory=list)  # (old, new): its name changed, its cells compared
    columns_renamed: list[tuple[str, str]] = field(default_factory=list)
    # (old header, new header): the old column's numbers are now under another header (headers corrected or
    # shifted), so changes reported under these headers may be relabelling, not new results
    columns_moved: list[tuple[str, str]] = field(default_factory=list)


def _norm(s: str) -> str:
    """A row or column name compared without case, spaces or LaTeX's braces and dollars (marks such as * and † are
    kept: "Swin-L (HTC++)" and "Swin-L (HTC++)*" are different rows)."""
    return re.sub(r"[\s{}$\\~]+", " ", s.lower()).strip()


CELL_NUMBER = re.compile(r"(?<![\d.])[-−]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)")


def cell_numbers(s: str) -> list[float]:
    r"""Every number a cell shows, in order: "89.3/82.1" is two results, and "47.1(±.2)" a result and its spread.

    >>> cell_numbers("89.3/82.1"), cell_numbers(r"72.0 (79.6/70.1)"), cell_numbers(r"47.1\textsubscript\pm.2")
    ([89.3, 82.1], [72.0, 79.6, 70.1], [47.1, 0.2])
    """
    return [float(n.replace("−", "-").replace(",", "")) for n in CELL_NUMBER.findall(s)]


def _dedupe(keys: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for k in keys:
        seen[_norm(k)] += 1  # names that only differ in spacing or case are the same name
        n = seen[_norm(k)]
        out.append(k if n == 1 else f"{k} ({n})")
    return out


def columns(t: Table) -> list[str]:
    """A key for each column: its header (spanning headers filled in over the columns they span), else its number."""
    width = max((len(r) for r in t.rows), default=0)
    head = []
    for k, r in enumerate(t.rows[: t.header_rows]):
        texts = [r[j].text if j < len(r) else "" for j in range(width)]
        if k < t.header_rows - 1:  # a spanning header row: \multicolumn leaves empty cells after its text
            for j in range(1, width):
                if not texts[j] and texts[j - 1] and j < len(r) and not r[j].raw:
                    texts[j] = texts[j - 1]
        head.append(texts)
    keys = [" ".join(h[j] for h in head if h[j]).strip() or f"column {j + 1}" for j in range(width)]
    return _dedupe(keys)


def rows(t: Table) -> list[tuple[int, str]]:
    """(row index, key) of the table's body rows: the key is the row's name cells (a \\multirow name filled down
    over the rows it spans); rows without a name are keyed by position."""
    out: list[tuple[int, str]] = []
    above: list[str] = []
    for i in range(t.header_rows, len(t.rows)):
        r = t.rows[i]
        if not any(c.text for c in r):
            continue
        start = t.row_start(i)
        names = [c.text for c in r[:start]]
        if start < len(r):  # a row of results: name cells left empty are filled down (\multirow)
            names = [n or (above[k] if k < len(above) else "") for k, n in enumerate(names)]
        if any(names):
            above = names
        out.append((i, " | ".join(n for n in names if n) or f"row {i + 1}"))
    keys = _dedupe([k for _, k in out])
    return [(i, k) for (i, _), k in zip(out, keys, strict=True)]


def _signature(t: Table) -> set[str]:
    return {_norm(k) for k in columns(t)} | {_norm(k) for _, k in rows(t)}


def match_tables(a: list[Table], b: list[Table]) -> list[tuple[int, int]]:
    """Pairs of the same table in two versions: by \\label, then caption, then rows and columns."""
    pairs: list[tuple[int, int]] = []
    used_a: set[int] = set()
    used_b: set[int] = set()

    def take(i: int, j: int) -> None:
        pairs.append((i, j))
        used_a.add(i)
        used_b.add(j)

    for i, t in enumerate(a):
        if t.label:
            j = next((j for j, u in enumerate(b) if j not in used_b and u.label == t.label), None)
            if j is not None:
                take(i, j)
    for score_of, threshold in (
        (lambda t, u: similarity(t.caption, u.caption) if t.caption and u.caption else 0.0, 0.6),
        (lambda t, u: len(_signature(t) & _signature(u)) / max(1, len(_signature(t) | _signature(u))), 0.5),
        (_same_shape, 0.25),  # every row renamed ("Completion" -> "Target Completion"): the same columns, as many rows, same file
    ):
        scored = sorted(
            ((score_of(t, u), i, j) for i, t in enumerate(a) if i not in used_a for j, u in enumerate(b) if j not in used_b),
            key=lambda c: (-c[0], c[1], c[2]),  # on a tie, the first of each
        )
        for score, i, j in scored:
            if score >= threshold and i not in used_a and j not in used_b:
                take(i, j)
    return sorted(pairs, key=lambda p: p[1])


def _same_shape(t: Table, u: Table) -> float:
    if t.file != u.file or len(t.rows) != len(u.rows):
        return 0.0
    ct, cu = {_norm(k) for k in columns(t)}, {_norm(k) for k in columns(u)}
    return 0.5 * len(ct & cu) / max(1, len(ct | cu))


SPREAD = re.compile(r"(?:±|\\pm|\+/-|\bstd\b|\bsd\b|\bse\b)[\s_{}()$]*$", re.I)
UNCLEAR = {"is", "em", "return", "success", "score", "rank", "time", "seconds", "second", "hours", "hour", "ms", "cost", "memory", "mem",
           "distance", "params", "parameters", "flops", "macs", "error", "errors", "loss", "map", "ap", "reward", "recall", "precision"}  # fmt: skip


def _is_spread(text: str, k: int) -> bool:
    r"""Whether the k-th number of a cell is the spread of the one before it (± 0.2, \pm 0.2, (std 0.2)).

    >>> _is_spread(r"4.1 $\pm$ 0.2", 1), _is_spread("89.3/82.1", 1), _is_spread("4.1 (std 0.3)", 1)
    (True, False, True)
    """
    spans = list(CELL_NUMBER.finditer(text))
    return 0 < k < len(spans) and bool(SPREAD.search(text[spans[k - 1].end() : spans[k].start()]))


def caption_direction(caption: str) -> str:
    """Which way is better, from a caption: an arrow or "higher/lower is better", or a metric named without doubt
    (BLEU, accuracy, FID), never words that are also plain English ("is", "time", "score").

    >>> caption_direction("BLEU scores on newstest2014."), caption_direction("Model sizes; the best is in bold.")
    ('higher', '')
    >>> caption_direction("Error (lower is better).")
    'lower'
    """
    if re.search(r"\\uparrow|↑|higher is better", caption, re.I):
        return "higher"
    if re.search(r"\\downarrow|↓|lower is better", caption, re.I):
        return "lower"
    ways = {"higher" for m in HIGHER.finditer(caption) if m.group(0).lower() not in UNCLEAR}
    ways |= {"lower" for m in LOWER.finditer(caption) if m.group(0).lower() not in UNCLEAR}
    return ways.pop() if len(ways) == 1 else ""


def _cell_text(t: Table, i: int, j: int) -> tuple[str, float | None, bool, int]:
    r = t.rows[i]
    if j >= len(r):
        return "", None, False, 0
    c = r[j]
    return c.text, c.value, c.bold, c.line


def diff_table(a: Table, b: Table) -> TableDiff:
    ca, cb = columns(a), columns(b)
    ra, rb = rows(a), rows(b)
    col_a = {_norm(k): j for j, k in enumerate(ca)}
    col_b = {_norm(k): j for j, k in enumerate(cb)}
    row_a = {_norm(k): i for i, k in ra}
    row_b = {_norm(k): i for i, k in rb}
    name = b.label or a.label or (f'"{b.caption[:60]}"' if b.caption else f"table at {b.file}:{b.line}")
    d = TableDiff("same", name, Where(a.name, a.file, a.line), Where(b.name, b.file, b.line))
    if _norm(a.caption) != _norm(b.caption):
        d.caption = (a.caption, b.caption)
    # columns whose header changed a little ("WikiSQL Accuracy (%)" -> "WikiSQL Acc. (%)"): paired by header, in order
    left_ca = [(j, k) for j, k in enumerate(ca) if _norm(k) not in col_b]
    left_cb = [(j, k) for j, k in enumerate(cb) if _norm(k) not in col_a]
    same_rows = [(i_a, row_b[_norm(k)]) for i_a, k in ra if _norm(k) in row_b]

    def column_agrees(x: int, y: int) -> bool:
        """Headers alike ("Accuracy (%)" -> "Acc. (%)") are one column if most of its numbers stayed; EN-DE and
        EN-RO are alike in name only."""
        ja, jb = left_ca[x][0], left_cb[y][0]
        pairs_ = [(a.rows[i][ja], b.rows[j][jb]) for i, j in same_rows if ja < len(a.rows[i]) and jb < len(b.rows[j])]
        numbers = [(p, q) for p, q in pairs_ if p.value is not None and q.value is not None]
        if numbers:
            return sum(p.value == q.value for p, q in numbers) >= 0.5 * len(numbers)
        return similarity(left_ca[x][1], left_cb[y][1]) >= 0.8

    for x, y in _pair([k for _, k in left_ca], [k for _, k in left_cb], 0.5):
        if not column_agrees(x, y):
            continue
        col_a[_norm(left_cb[y][1])] = left_ca[x][0]
        d.columns_renamed.append((left_ca[x][1], left_cb[y][1]))
    renamed_cols = {o for o, _ in d.columns_renamed} | {n for _, n in d.columns_renamed}
    d.columns_added = [k for k in cb if _norm(k) not in col_a and k not in renamed_cols]
    d.columns_removed = [k for k in ca if _norm(k) not in col_b and k not in renamed_cols]
    # rows whose name changed a little ("ALBERT | xlarge | 59M" -> "... | 60M"): paired by name, in order; between
    # rows named alike, the one whose numbers are the old row's ("Adapter | 11.48M" is "Adapter^L | 11.09M", not
    # "Adapter^L | 0.37M")
    left_a = [(i, k) for i, k in ra if _norm(k) not in row_b]
    left_b = [(i, k) for i, k in rb if _norm(k) not in row_a]
    shared = [(col_a[_norm(k)], j) for j, k in enumerate(cb) if _norm(k) in col_a]

    def same_numbers(x: int, y: int) -> float:
        ra_, rb_ = a.rows[left_a[x][0]], b.rows[left_b[y][0]]
        cells = [(ra_[ja], rb_[jb]) for ja, jb in shared if ja < len(ra_) and jb < len(rb_) and ra_[ja].value is not None]
        return sum(p.value == q.value for p, q in cells) / len(cells) if cells else 0.0

    renamed: dict[int, int] = {}
    for x, y in _pair([k for _, k in left_a], [k for _, k in left_b], 0.6, same_numbers):
        renamed[left_b[y][0]] = left_a[x][0]
        d.rows_renamed.append((left_a[x][1], left_b[y][1]))
    renamed_a = set(renamed.values())
    d.rows_added = [k for i, k in left_b if i not in renamed]
    d.rows_removed = [k for i, k in left_a if i not in renamed_a]
    for i_b, rkey in rb:
        i_a = row_a.get(_norm(rkey), renamed.get(i_b))
        if i_a is None:
            continue
        first = min(a.row_start(i_a), b.row_start(i_b))
        for j_b, ckey in enumerate(cb):
            j_a = col_a.get(_norm(ckey))
            if j_a is None or j_b < first:
                continue
            t_a, v_a, bold_a, _ = _cell_text(a, i_a, j_a)
            t_b, v_b, bold_b, line = _cell_text(b, i_b, j_b)
            if v_a is not None and v_b is not None:
                kind = "value" if v_a != v_b else "bold" if bold_a != bold_b else ""
                na, nb = cell_numbers(t_a), cell_numbers(t_b)
                if kind != "value" and na != nb:  # another number in the cell changed: "89.3/82.1" -> "89.3/82.3"
                    k = next((k for k, (x, y) in enumerate(zip(na, nb, strict=False)) if x != y), None)
                    if k is not None and not (_is_spread(t_a, k) or _is_spread(t_b, k)):
                        kind, v_a, v_b = "value", na[k], nb[k]
                    else:  # a spread that changed ("4.1 ± 0.2" -> "4.1 ± 0.5"), or a number added or dropped beside it
                        kind = "text"
            else:
                kind = "text" if _norm(t_a) != _norm(t_b) else ""
            if not kind:
                continue
            better = None
            if kind == "value" and v_a is not None and v_b is not None:
                way = direction(ckey) or caption_direction(b.caption)  # "BLEU scores" over columns named EN-DE, EN-FR
                better = (v_b > v_a) == (way == "higher") if way else None
            d.cells.append(CellChange(rkey, ckey, t_a, t_b, v_a, v_b, kind, bold_a, bold_b, line, better))
    d.columns_moved = _moved_columns(a, b, ca, cb, [(i_a, row_b[_norm(k)]) for i_a, k in ra if _norm(k) in row_b], d)
    if d.cells or d.caption or d.rows_added or d.rows_removed or d.columns_added or d.columns_removed or d.rows_renamed or d.columns_renamed:
        d.status = "changed"
    return d


def _moved_columns(a: Table, b: Table, ca: list[str], cb: list[str], same_rows: list[tuple[int, int]], d: TableDiff) -> list[tuple[str, str]]:
    """Old columns whose numbers now stand under another header: BLIP-2 v1 labelled its VQAv2 columns "val, test-dev"
    and v3 "test-dev, test-std", with the same numbers. Each column whose values changed under its own header is
    looked for among the new columns."""
    changed_cols = {c.column for c in d.cells if c.kind == "value"}
    out = []
    for ja, key in enumerate(ca):
        if key not in changed_cols and key in cb:
            continue

        def numbers(t: Table, j: int, side: int) -> list[float | None]:
            return [t.rows[pair[side]][j].value if j < len(t.rows[pair[side]]) else None for pair in same_rows]

        old = numbers(a, ja, 0)
        if sum(v is not None for v in old) < 2:
            continue
        for jb, other in enumerate(cb):
            if _norm(other) == _norm(key):
                continue
            new = numbers(b, jb, 1)
            both = [(x, y) for x, y in zip(old, new, strict=True) if x is not None and y is not None]
            if len(both) >= 2 and sum(x == y for x, y in both) >= 0.8 * len(both) >= 0.8 * sum(v is not None for v in old):
                out.append((key, other))
                break
    return out


def diff_tables(a: list[Table], b: list[Table]) -> list[TableDiff]:
    a = [t for t in a if len(t.rows) > t.header_rows]
    b = [t for t in b if len(t.rows) > t.header_rows]
    pairs = match_tables(a, b)
    paired_a = {i for i, _ in pairs}
    by_b = dict((j, i) for i, j in pairs)
    out = []
    for j, t in enumerate(b):
        if j in by_b:
            out.append(diff_table(a[by_b[j]], t))
        else:
            out.append(TableDiff("added", t.label or t.name, None, Where(t.name, t.file, t.line), rows_added=[k for _, k in rows(t)]))
    for i, t in enumerate(a):
        if i not in paired_a:
            out.append(TableDiff("removed", t.label or t.name, Where(t.name, t.file, t.line), None, rows_removed=[k for _, k in rows(t)]))
    return out


# ---------------------------------------------------------------- figures, authors, references


@dataclass
class FigureDiff:
    status: str  # "same", "changed", "added", "removed"
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
    """A name compared without accents, case or middle initials: "Ed H. Chi" is "Ed Chi".

    >>> _person("Ed H. Chi") == _person("Ed Chi"), _person("Björn Ommer")
    (True, 'bjorn ommer')
    """
    s = unicodedata.normalize("NFKD", name)
    words = re.findall(r"[^\W\d_]+", "".join(c for c in s if not unicodedata.combining(c)).lower())  # any script
    return " ".join([words[0], words[-1]] if len(words) > 2 else words)


@dataclass
class AuthorDiff:
    old: list[str]
    new: list[str]
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    reordered: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.reordered)


def diff_authors(a: list[str], b: list[str]) -> AuthorDiff:
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
