"""arxiv-diff watch, against a fake arXiv (made-up ids and papers; no network)."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from helpers import write
from test_cli import _tar

from arxiv_diff.arxiv import Client
from arxiv_diff.cli import main
from arxiv_diff.watch import ids_in_bib, parse_feed, read_inputs

BIB = r"""@article{lora, title={LoRA}, eprint={2501.00001v1}, archivePrefix={arXiv}}
@misc{attn, title={Attention}, howpublished={\url{https://arxiv.org/abs/2501.00002}}}
@inproceedings{old, title={An old one}, note={arXiv:hep-th/9901001}}
@article{doi, title={By DOI}, doi={10.48550/arXiv.2501.00003}}
@article{gone, title={Withdrawn}, journal={arXiv preprint arXiv:2501.09999}}
@book{none, title={No arXiv id}}
"""


def entry(aid: str, v: int, updated: str, title: str, comment: str = "", journal: str = "") -> str:
    extra = (f"<arxiv:comment>{comment}</arxiv:comment>" if comment else "") + (
        f"<arxiv:journal_ref>{journal}</arxiv:journal_ref>" if journal else ""
    )
    return (
        f"<entry><id>http://arxiv.org/abs/{aid}v{v}</id><updated>{updated}T10:00:00Z</updated>"
        f"<published>2025-01-02T10:00:00Z</published><title>{title}</title>{extra}</entry>"
    )


class FakeApi:
    def __init__(self, tmp: Path) -> None:
        self.versions = {
            "2501.00001": (2, "2025-03-01", "Low-Rank Adaptation", "ICLR 2026 camera-ready", ""),
            "2501.00002": (1, "2025-01-02", "Attention", "", ""),
            "hep-th/9901001": (3, "2001-01-01", "An old one", "", "Phys. Rev. D 1 (2001)"),
            "2501.00003": (1, "2025-01-05", "By DOI", "", ""),
        }
        self.urls: list[str] = []
        self.sources = {1: _tar(write(tmp / "s1")), 2: _tar(write(tmp / "s2", BIG="28.9"))}

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        if "oai2" in url:  # the versions and their dates: v1 on 2025-01-02, one a month after, the last on its date
            aid = url.split("oai:arXiv.org:")[1].split("&")[0]
            n, last = self.versions[aid][0], self.versions[aid][1]
            dates = [f"2025-{k + 1:02d}-02" for k in range(n - 1)] + [last]
            vs = "".join(
                f'<version version="v{k + 1}"><date>{d[8:]} Jan 2025 10:00:00 GMT</date></version>'.replace(
                    "Jan", ["Jan", "Feb", "Mar", "Apr", "May", "Jun"][int(d[5:7]) - 1]
                )
                for k, d in enumerate(dates)
            )
            return (
                '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord><record><metadata>'
                f'<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>{aid}</id><title>x</title>{vs}</arXivRaw></metadata></record></GetRecord></OAI-PMH>'
            ).encode()
        if "/api/query" in url:
            ids = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["id_list"][0].split(",")
            body = "".join(entry(a, *self.versions[a]) for a in ids if a in self.versions)
            if "2501.09999" in ids:
                body += "<entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_2501.09999</id><title>Error</title></entry>"
            return f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">{body}</feed>'.encode()
        return self.sources[int(url.rsplit("v", 1)[1])]

    def client(self) -> Client:
        return Client(self.get, interval=3.0, sleep=lambda s: None)


def test_ids_in_a_bib():
    found = ids_in_bib(BIB)
    assert sorted(found) == ["2501.00001", "2501.00002", "2501.00003", "2501.09999", "hep-th/9901001"]
    assert found["2501.00001"].version == 1 and found["2501.00001"].keys == ["lora"]
    assert found["2501.00002"].version is None and found["hep-th/9901001"].keys == ["old"]


def test_inputs_of_every_kind(tmp_path):
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "refs.bib").write_text(BIB, encoding="utf-8")
    (tmp_path / "list.txt").write_text("# papers I follow\n2501.00002\nhttps://arxiv.org/abs/2501.00004v2\n", encoding="utf-8")
    found = read_inputs([str(tmp_path / "paper"), str(tmp_path / "list.txt"), "2501.00005"])
    assert {"2501.00001", "2501.00004", "2501.00005"} <= set(found) and found["2501.00004"].version == 2


def test_feed_skips_error_entries():
    xml = f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">{entry("2501.00001", 4, "2025-05-05", "X  Y")}'
    xml += "<entry><id>http://arxiv.org/api/errors#bad</id><title>Error</title></entry></feed>"
    (lat,) = parse_feed(xml.encode()).values()
    assert (lat.arxiv_id, lat.version, lat.updated, lat.title) == ("2501.00001", 4, "2025-05-05", "X Y")


def test_first_run_then_a_new_version(tmp_path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    api = FakeApi(tmp_path)
    # first run: only the paper whose .bib entry names an older version (lora v1, now v2) is reported
    assert main(["watch", str(bib), "--fail-on-new"], api.client()) == 1
    out = capsys.readouterr().out
    assert "2501.00001  v1 → v2  (2025-03-01)  Low-Rank Adaptation" in out and "cited as: lora" in out
    assert "comments: ICLR 2026 camera-ready" in out and "Not found on arXiv: 2501.09999" in out
    assert len([u for u in api.urls if "/api/query" in u]) == 1  # one batch for all of them
    state = json.loads((tmp_path / "refs.arxiv-watch.json").read_text(encoding="utf-8"))
    assert state["papers"]["2501.00002"]["version"] == 1
    # nothing new: nothing reported
    assert main(["watch", str(bib)], api.client()) == 0
    assert "No new versions among 5 arXiv papers" in capsys.readouterr().out
    # attention posts v2, the old paper gets... nothing; LoRA nothing
    api.versions["2501.00002"] = (2, "2025-06-01", "Attention", "Accepted at NeurIPS", "")
    assert main(["watch", str(bib), "--format", "json", "--diff"], api.client()) == 0
    payload = json.loads(capsys.readouterr().out)
    (n,) = payload["new"]
    assert (n["arxiv_id"], n["old_version"], n["new_version"]) == ("2501.00002", 1, 2)
    assert any("BLEU" in line or "result" in line for line in n["summary"]), n["summary"]  # what changed, results first


def test_newly_published_and_dry_run(tmp_path, capsys):
    api = FakeApi(tmp_path)
    state = tmp_path / "s.json"
    api.versions["hep-th/9901001"] = (3, "2001-01-01", "An old one", "", "")
    assert main(["watch", "hep-th/9901001", "--state", str(state)], api.client()) == 0
    assert "Now watching 1 arXiv paper" in capsys.readouterr().out
    api.versions["hep-th/9901001"] = (3, "2001-01-01", "An old one", "", "Phys. Rev. D 1 (2001)")
    assert main(["watch", "hep-th/9901001", "--state", str(state), "--format", "markdown", "--dry-run"], api.client()) == 0
    md = capsys.readouterr().out
    assert "now published: Phys. Rev. D 1 (2001)" in md and "| v3 |" in md
    assert "journal_ref" in state.read_text(encoding="utf-8") and '"journal_ref": ""' in state.read_text(encoding="utf-8")  # dry run: unchanged


def test_since_a_date(tmp_path, capsys):
    api = FakeApi(tmp_path)
    api.versions["2501.00001"] = (4, "2025-05-20", "Low-Rank Adaptation", "", "")  # v1 Jan, v2 Feb, v3 Mar, v4 May
    assert main(["watch", "2501.00001", "--since", "2025-02-15", "--state", str(tmp_path / "u.json")], api.client()) == 0
    assert "v2 → v4" in capsys.readouterr().out  # v2 was the latest on the date
    api.versions["2501.00001"] = (2, "2025-03-01", "Low-Rank Adaptation", "ICLR 2026 camera-ready", "")
    assert main(["watch", "2501.00001", "--since", "2025-02-01", "--state", str(tmp_path / "s.json")], api.client()) == 0
    assert "v1 → v2" in capsys.readouterr().out
    assert main(["watch", "2501.00001", "--since", "2025-04-01", "--state", str(tmp_path / "t.json")], api.client()) == 0
    assert "Now watching" in capsys.readouterr().out


def test_bad_inputs(tmp_path, capsys):
    api = FakeApi(tmp_path)
    empty = tmp_path / "e.bib"
    empty.write_text("@book{x, title={y}}", encoding="utf-8")
    assert main(["watch", str(empty)], api.client()) == 2
    bad_state = tmp_path / "bad.json"
    bad_state.write_text("[1, 2]", encoding="utf-8")
    assert main(["watch", "2501.00001", "--state", str(bad_state)], api.client()) == 2
    assert "not a watch state file" in capsys.readouterr().err


def test_busy_arxiv_is_asked_again(tmp_path, capsys):
    from arxiv_diff.arxiv import FetchError

    api = FakeApi(tmp_path)
    answers = iter([FetchError("arxiv.org: HTTP 429 for x"), None])
    waits: list[float] = []

    def get(url: str) -> bytes:
        failure = next(answers)
        if failure:
            raise failure
        return api.get(url)

    client = Client(get, interval=0.0, sleep=waits.append)
    assert main(["watch", "2501.00001", "--state", str(tmp_path / "s.json")], client) == 0
    assert 15.0 in waits and "Now watching 1" in capsys.readouterr().out
    gone = Client(lambda url: (_ for _ in ()).throw(FetchError("arxiv.org: HTTP 404 for x")), interval=0.0, sleep=waits.append)
    assert main(["watch", "2501.00001", "--state", str(tmp_path / "t.json")], gone) == 2
