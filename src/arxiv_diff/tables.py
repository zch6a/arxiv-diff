"""Tables compared: paired by label, caption, rows and columns; cells by row name and column header (renamed rows
and columns paired by name and by the numbers they hold); value, text and bold changes with better/worse where
the metric says; numbers that moved under another header pointed out."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from paper_proof.tables import HIGHER, LOWER, Table, direction

from .words import Status, Where, _pair, similarity


@dataclass
class CellChange:
    row: str
    column: str
    old: str  # the cell as text
    new: str
    old_value: float | None
    new_value: float | None
    kind: Literal["value", "text", "bold"]  # a number changed; the cell changed otherwise; only the bold marking
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
    status: Status
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
    r"""Which way is better, from a caption: an arrow or "higher/lower is better", or a metric named without doubt
    (BLEU, accuracy, FID), never words that are also plain English ("is", "time", "score").

    >>> caption_direction("BLEU scores on newstest2014."), caption_direction("Model sizes; the best is in bold.")
    ('higher', '')
    >>> caption_direction("Error (lower is better).")
    'lower'
    >>> caption_direction(r"$\uparrow$/$\downarrow$: higher/lower is better."), caption_direction("FID and IS on ImageNet.")
    ('', '')
    """
    up = bool(re.search(r"\\uparrow|↑|higher is better", caption, re.I))
    down = bool(re.search(r"\\downarrow|↓|lower is better", caption, re.I))
    if up or down:
        return "" if up and down else "higher" if up else "lower"  # both: each column has its own
    # a word that is also plain English counts only written as a metric (IS, EM, mAP), not as a word ("is", "map")
    clear = lambda m: m.group(0).lower() not in UNCLEAR or not m.group(0).islower()  # noqa: E731
    ways = {"higher" for m in HIGHER.finditer(caption) if clear(m)} | {"lower" for m in LOWER.finditer(caption) if clear(m)}
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
            kind: Literal["value", "text", "bold", ""]
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
