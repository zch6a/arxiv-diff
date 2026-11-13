"""Words and numbers: tokens, word diffs, the numbers that changed in a sentence, how alike two texts are, and
pairing similar texts in order. Used by the comparison of sentences, sections, tables and figures."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher

# a URL; a DOI; a citation's keys, whole ([huang2019evaluating] is not the year 2019); a reference ‹label›; a number (a minus sign only where
# a sign can be: not the hyphen of WikiText-103); a command; a word; a mark
TOKEN = re.compile(
    r"\s*(?:https?://[^\s)\]]+[^\s)\].,;:]|\b10\.\d{4,9}/[^\s,;]+[^\s,;.)]|\[(?=[^\]]*[A-Za-z])[^\[\]]{1,300}\]|‹[^›]{0,300}›"
    r"|(?:(?<![\w)])[-−])?\d+(?:[.,]\d+)*"
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


MATH = re.compile(r"(?<!\\)\$((?:\\.|[^$\\]){1,4000})\$|\\\(((?:.|\n){0,4000}?)\\\)")


PLAIN_NUMBER = re.compile(r"\s*(?:\\sim|\\approx|<|>|\\le|\\ge)?\s*([-+−]?\d+(?:[.,]\d+)*)\s*(?:\\%|%)?\s*")


def _math_out(s: str) -> str:
    r"""A sentence with its formulas set aside, a number written in math mode ($28.4$, $\sim 2.0$) kept: the numbers
    of a sentence are its results, not the coefficients and exponents of its formulas (whose changes the word diff
    shows).

    >>> _math_out(r"We reach $28.4$ BLEU, since $\frac{1}{2} x^2 \le 3$.")
    'We reach 28.4 BLEU, since ⟨math⟩.'
    """

    def keep(m: re.Match[str]) -> str:
        body = m.group(1) if m.group(1) is not None else m.group(2)
        plain = PLAIN_NUMBER.fullmatch(body)
        return plain.group(1) if plain else "⟨math⟩"

    return MATH.sub(keep, s)


def number_changes(a: str, b: str) -> list[NumberChange]:
    """The numbers that changed between two versions of a sentence, each with the words around it.

    >>> old, new = "BLEU of 28.4 on EN-DE and 41.0 on EN-FR.", "BLEU of 28.9 on EN-DE and 41.0 on EN-FR."
    >>> [(n.old, n.new, n.before, n.after) for n in number_changes(old, new)]
    [('28.4', '28.9', 'BLEU of', 'on EN-DE')]
    >>> number_changes("as high as 12288 [smith2019]", "as high as 12,288 [smith2020]"), number_changes("of 42k examples", "of 42,000 examples")
    ([], [])
    """
    ta, tb = tokens(_math_out(a)), tokens(_math_out(b))
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


@dataclass
class Where:
    name: str
    file: str
    line: int
