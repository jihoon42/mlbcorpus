"""노트북을 네트워크 없이 실행해 본다: requests.get 을 캐시된 응답으로 바꾼 셀을 맨 앞에 끼워 nbclient 로 돌린다.

    uv run --with nbformat --with nbclient --with ipykernel --with matplotlib python notebooks/test_playground_offline.py

캐시: data/raw/games/2026/824464/*.json.gz, data/raw/schedule/2026_R.json.gz
hydrate 붙은 schedule 은 캐시가 없으므로 그날 경기 목록에 824464 의 content 만 붙여 흉내 낸다.
"""

from __future__ import annotations

import pathlib
import sys

import nbformat
from nbclient import NotebookClient

ROOT = pathlib.Path(__file__).resolve().parents[1]

FAKE = r'''
import gzip, json, re, pathlib
import requests as _requests
_ROOT = pathlib.Path(%r)
_GAME = _ROOT / "data/raw/games/2026/824464"
_SCHED = json.load(gzip.open(_ROOT / "data/raw/schedule/2026_R.json.gz"))
_CALLS = []

class _Resp:
    def __init__(self, data): self._d, self.status_code = data, 200
    def json(self): return self._d
    def raise_for_status(self): pass

def _day(date, hydrate=False):
    days = [d for d in _SCHED["dates"] if d["date"] == date]
    if not days:
        return {"dates": []}
    day = json.loads(json.dumps(days[0]))
    if hydrate:
        content = json.load(gzip.open(_GAME / "content.en.json.gz"))
        for g in day["games"]:
            if g["gamePk"] == 824464:
                g["content"] = {"editorial": content["editorial"]}
    return {"dates": [day]}

def _fake_get(url, params=None, headers=None, timeout=None):
    params = params or {}
    _CALLS.append((url, dict(params)))
    if url.endswith("/v1/schedule"):
        return _Resp(_day(params["date"], hydrate="hydrate" in params))
    m = re.search(r"/game/(\d+)/(feed/live|content|winProbability)$", url)
    assert m and m.group(1) == "824464", url
    kind = m.group(2)
    name = {"feed/live": "feed", "winProbability": "winprob"}.get(kind, "content." + params.get("language", "en"))
    return _Resp(json.load(gzip.open(_GAME / f"{name}.json.gz")))

_requests.get = _fake_get
print("fake requests.get installed")
'''


def main() -> int:
    nb = nbformat.read(ROOT / "notebooks/mlb_playground.ipynb", as_version=4)
    if "--variant" in sys.argv:  # 분기 검사: 단어 바꾸기, 타석 번호 범위 밖
        for c in nb.cells:
            if c.cell_type == "code":
                c.source = c.source.replace('word = "clutch"', 'word = "Tucker"').replace("at_bat = 2 #@param", "at_bat = 99 #@param")
    nb.cells.insert(0, nbformat.v4.new_code_cell(FAKE % str(ROOT)))
    client = NotebookClient(nb, timeout=120, kernel_name="python3", allow_errors=False)
    client.execute()
    failures = 0
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        title = cell.source.splitlines()[0][:50]
        texts = []
        for out in cell.get("outputs", []):
            if out.output_type == "stream":
                texts.append(out.text)
            elif out.output_type in ("execute_result", "display_data"):
                texts.append(out.data.get("text/plain", "")[:1500])
                if "image/png" in out.data:
                    import base64
                    png = ROOT / "notebooks" / f"_cell{i}.png"
                    png.write_bytes(base64.b64decode(out.data["image/png"]))
                    texts.append(f"[png saved: {png}]")
            elif out.output_type == "error":
                failures += 1
                texts.append("ERROR " + out.ename + ": " + out.evalue)
        joined = "\n".join(texts)
        print(f"\n===== cell {i}: {title} =====")
        print(joined[:2500])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
