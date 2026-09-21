"""notebooks/mlb_playground.ipynb 를 생성한다.  `uv run python notebooks/build_playground.py`

노트북은 저장소에 의존하지 않는 독립 실행형이다 (requests · pandas · matplotlib 만 사용, Colab 기본 환경).
셀은 Colab 폼(#@param)으로 만들어 코드가 접힌 채 입력칸과 결과만 보이게 한다.
"""

from __future__ import annotations

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

INTRO = """\
# MLB 경기 텍스트 놀이터

우리 팀 프로젝트가 다루는 데이터를 직접 받아서 눈으로 보는 노트북입니다. 설치할 것은 없고, 각 셀 왼쪽의 ▶ 를 위에서부터 차례로 누르면 됩니다 (또는 메뉴 **런타임 → 모두 실행**).

각 셀에는 입력칸이 있습니다. 날짜, 경기 번호, 타석 번호, 단어를 바꾸고 다시 ▶ 를 누르면 그 값으로 다시 받아옵니다. 코드는 접혀 있고, 보고 싶으면 셀 오른쪽의 **코드 표시**를 누르면 됩니다.

여기서 받는 자료는 MLB 공식 사이트가 열어 둔 주소에서 그 자리에서 가져오는 것이고, 로그인이나 열쇠는 필요 없습니다. 같은 주소를 브라우저에 붙여 넣어도 똑같은 내용이 보입니다.

순서: **0** 준비 → **1** 날짜로 경기 목록 → **2** 경기 하나의 타석 79개 → **3** 캡션과 기사 → **4** 같은 플레이, 세 가지 말투 → **5** 승리확률 그래프 → **6** 단어 찾기
"""

SETUP = '''#@title 0. 준비 (한 번만 실행) { display-mode: "form" }
import html, re, unicodedata, json
import requests
import pandas as pd

BASE = "https://statsapi.mlb.com/api"
HEADERS = {"User-Agent": "mlb-playground/0.1 (course project; Hongik Univ.)", "Accept": "application/json"}

def get(path, **params):
    """statsapi 에서 JSON 을 받아온다. path 는 'v1/schedule' 처럼 BASE 뒤에 붙는 부분."""
    r = requests.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def strip_accents(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

_EMBED = re.compile(r"<(iframe|script|blockquote|style)\\b.*?</\\1\\s*>", re.S | re.I)
_MDLINK = re.compile(r"\\[([^\\]]+)\\]\\((?:https?:)?//[^)]*\\)")
_TAG = re.compile(r"<[^>]+>")

def recap_paragraphs(body):
    """리캡 HTML → (데이트라인, 단락 목록)."""
    body = _EMBED.sub(" ", body or "")
    out = []
    for chunk in re.split(r"</?p\\b[^>]*>", body):
        for para in re.split(r"\\n\\s*\\n", chunk):
            t = html.unescape(_TAG.sub("", _MDLINK.sub(r"\\1", para))).replace("**", "")
            t = re.sub(r"\\s+", " ", t).strip()
            if t and not t.startswith("*"):
                out.append(t)
    dateline = ""
    if out:
        m = re.match(r"^([A-Z][A-Z .\\'\\-]{1,40}?) -- ", out[0])
        if m:
            dateline, out[0] = m.group(1).strip(), out[0][m.end():]
    return dateline, out

_ABBR = ("No.", "Mr.", "Mrs.", "Ms.", "Dr.", "Jr.", "Sr.", "St.", "vs.", "L.A.", "N.L.", "A.L.", "U.S.", "D.C.")
_SPLIT = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\\"\\u201d\\u2019)]))\\s+(?=[\\"\\u201c(]?[A-Z0-9])")

def sentences(paragraph):
    p = paragraph
    for a in _ABBR:
        p = p.replace(a, a.replace(".", "\\x00"))
    return [s.replace("\\x00", ".").strip() for s in _SPLIT.split(p) if s.strip()]

def show(df, caption=None):
    """표 출력. Colab 이면 정렬·검색되는 표로."""
    if caption:
        print(caption)
    try:
        from google.colab import data_table  # Colab 에서만 있음
        data_table.enable_dataframe_formatter()
    except Exception:
        pass
    pd.set_option("display.max_colwidth", 200)
    pd.set_option("display.width", 200)
    display(df)

STATE = {}  # 셀 사이에 넘겨 주는 값 (받아 둔 경기 등)
print("준비 완료. 다음 셀로 가세요.")
'''

CELL1 = '''#@title 1. 날짜로 그날 경기 목록 { display-mode: "form" }
#@markdown 날짜를 고르고 ▶. 미국 날짜 기준이라 한국에서 본 경기는 보통 하루 전 날짜입니다.
date = "2026-09-17" #@param {type:"date"}

sched = get("v1/schedule", sportId=1, date=date)
rows = []
for day in sched.get("dates", []):
    for g in day["games"]:
        a, h = g["teams"]["away"], g["teams"]["home"]
        rows.append({
            "경기 번호": g["gamePk"],
            "원정": a["team"]["name"],
            "홈": h["team"]["name"],
            "점수 (원정-홈)": f'{a.get("score", "")}-{h.get("score", "")}' if "score" in a else "",
            "상태": g["status"]["detailedState"],
            "구장": g.get("venue", {}).get("name", ""),
        })
games_df = pd.DataFrame(rows)
if games_df.empty:
    print(f"{date} 에는 경기가 없습니다. 다른 날짜를 골라 보세요.")
else:
    show(games_df, f"{date} 경기 {len(games_df)}개. 상태가 Final 인 경기의 번호를 다음 셀에 넣으세요.")
'''

CELL2 = '''#@title 2. 경기 하나의 타석 전체 { display-mode: "form" }
#@markdown 위 표의 경기 번호를 넣고 ▶. 타석마다 기록원이 남긴 공식 문장이 한 줄씩 나옵니다.
game_pk = 824464 #@param {type:"integer"}

feed = get(f"v1.1/game/{game_pk}/feed/live")
gd, ld = feed["gameData"], feed["liveData"]
away, home = gd["teams"]["away"], gd["teams"]["home"]
plays = ld["plays"]["allPlays"]
HALF = {"top": "초", "bottom": "말"}

rows = []
for p in plays:
    r, ab, m = p["result"], p["about"], p["matchup"]
    pitches = [e for e in p.get("playEvents", []) if e.get("isPitch")]
    hit = (pitches[-1].get("hitData") if pitches else None) or {}
    rows.append({
        "타석": ab["atBatIndex"],
        "이닝": f'{ab["inning"]}{HALF.get(ab["halfInning"], "")}',
        "타자": m["batter"]["fullName"],
        "투수": m["pitcher"]["fullName"],
        "결과": r.get("event", ""),
        "점수": f'{r.get("awayScore", "")}-{r.get("homeScore", "")}',
        "기록 문장": r.get("description", "").strip(),
        "투구 수": len(pitches),
        "타구 속도(mph)": hit.get("launchSpeed"),
        "비거리(ft)": hit.get("totalDistance"),
        "흥미도": ab.get("captivatingIndex"),
    })
plays_df = pd.DataFrame(rows)

STATE.update(game_pk=game_pk, feed=feed, plays=plays, plays_df=plays_df,
             label=f'{away["abbreviation"]}@{home["abbreviation"]} {gd["datetime"]["officialDate"]}')
score = ld["linescore"]["teams"]
print(f'{away["name"]} @ {home["name"]}, {gd["datetime"]["officialDate"]}, {gd.get("venue", {}).get("name", "")}')
print(f'최종 {away["abbreviation"]} {score["away"].get("runs")} - {score["home"].get("runs")} {home["abbreviation"]}  |  '
      f'타석 {len(plays)}개, 투구 {int(plays_df["투구 수"].sum())}개, 상태 {gd["status"]["detailedState"]}')
show(plays_df.drop(columns=["투구 수"]))
'''

CELL3 = '''#@title 3. 같은 경기의 하이라이트 캡션과 리캡 기사 { display-mode: "form" }
#@markdown 2번 셀에서 받은 경기의 다른 두 겹의 글. 캡션은 영상 편집자가, 기사는 MLB.com 기자가 씁니다.
if "feed" not in STATE:
    print("먼저 2번 셀을 실행하세요.")
    pk = None
else:
    pk = STATE["game_pk"]
content = get(f"v1/game/{pk}/content") if pk else {}
content_es = get(f"v1/game/{pk}/content", language="es") if pk else {}
STATE.update(content=content, content_es=content_es)

# 투구 ID → 타석 번호 (캡션이 어느 타석에 붙는지)
pid_to_ab = {e["playId"]: p["about"]["atBatIndex"]
             for p in STATE.get("plays", []) for e in p.get("playEvents", []) if e.get("playId")}
items = ((content.get("highlights") or {}).get("highlights") or {}).get("items") or []
cap_rows = [{"붙는 타석": pid_to_ab.get(h.get("guid"), ""), "제목": h.get("title", ""), "캡션": h.get("description", "")}
            for h in items]
captions_df = pd.DataFrame(cap_rows, columns=["붙는 타석", "제목", "캡션"])
if pk:
    STATE["captions_df"] = captions_df
    show(captions_df, f"하이라이트 {len(items)}개 (타석 번호가 있는 것은 특정 투구에 정확히 붙는 영상)")

def recap_of(c):
    return ((c.get("editorial") or {}).get("recap") or {}).get("mlb") or {}

rec, rec_es = recap_of(content), recap_of(content_es)
if not pk:
    pass
elif not rec.get("body"):
    print("\\n이 경기에는 리캡 기사가 없습니다 (더블헤더나 순연 경기에 가끔 있음).")
    STATE["recap_sentences"] = []
else:
    dateline, paras = recap_paragraphs(rec["body"])
    sents = [s for para in paras for s in sentences(para)]
    STATE["recap_sentences"] = sents
    print("\\n=== 리캡 기사 (영어) ===")
    print(rec.get("headline", ""), "|", ", ".join(c.get("name", "") for c in rec.get("contributors", [])),
          f"| 단락 {len(paras)}, 문장 {len(sents)}")
    for i, para in enumerate(paras, 1):
        print(f"\\n[{i}] {para}")
    if rec_es.get("body"):
        _, paras_es = recap_paragraphs(rec_es["body"])
        print("\\n=== 같은 경기 스페인어판 ===")
        print(rec_es.get("headline", ""), f"| 단락 {len(paras_es)}")
        print(paras_es[0] if paras_es else "")
'''

CELL4 = '''#@title 4. 같은 플레이, 세 가지 말투 { display-mode: "form" }
#@markdown 타석 번호(2번 표의 첫 열)를 넣고 ▶. 기록 문장, 캡션, 기사 문장을 나란히 놓습니다.
at_bat = 2 #@param {type:"integer"}

def _three_registers(at_bat):
    if "captions_df" not in STATE:
        print("먼저 2번, 3번 셀을 실행하세요."); return
    plays = STATE["plays"]
    if not 0 <= at_bat < len(plays):
        print(f"타석 번호는 0부터 {len(plays) - 1} 사이입니다."); return
    _show_three(at_bat, plays[at_bat])

def _show_three(at_bat, p):
    r, ab, m = p["result"], p["about"], p["matchup"]

    if "winprob" not in STATE:
        STATE["winprob"] = {w["atBatIndex"]: w for w in get(f'v1/game/{STATE["game_pk"]}/winProbability')}
    w = STATE["winprob"].get(at_bat, {})
    batting_home = ab["halfInning"] == "bottom"
    wpa = w.get("homeTeamWinProbabilityAdded")
    wpa_bat = None if wpa is None else (wpa if batting_home else -wpa)

    pitches = [e for e in p.get("playEvents", []) if e.get("isPitch")]
    hit = (pitches[-1].get("hitData") if pitches else None) or {}
    HALF = {"top": "초", "bottom": "말"}
    print(f'타석 #{at_bat}  {ab["inning"]}회{HALF.get(ab["halfInning"], "")}  {m["batter"]["fullName"]} vs {m["pitcher"]["fullName"]}  →  {r.get("event", "")}')
    print()
    print("① 공식 기록 문장:", r.get("description", "").strip())

    caps = STATE["captions_df"]
    mine = caps[caps["붙는 타석"] == at_bat]
    if mine.empty:
        print("② 캡션: 이 타석에 붙은 하이라이트 영상이 없습니다.")
    for _, c in mine.iterrows():
        print("② 캡션:", c["캡션"] or c["제목"])

    players = STATE["feed"]["gameData"]["players"]
    batter = players.get(f'ID{m["batter"]["id"]}', {})
    last = strip_accents(batter.get("lastName") or m["batter"]["fullName"].split()[-1])
    hits = [s for s in STATE.get("recap_sentences", []) if re.search(rf"\\b{re.escape(last)}\\b", strip_accents(s))]
    if not hits:
        print(f"③ 기사: {m['batter']['fullName']} 을(를) 언급한 문장이 없습니다.")
    for s in hits:
        print("③ 기사:", s)

    print()
    print("수치:",
          f"공격팀 승률 변화 {wpa_bat:+.1f}%p" if wpa_bat is not None else "승률 변화 없음",
          f'| 레버리지 {w.get("leverageIndex")}' if w.get("leverageIndex") is not None else "",
          f'| 흥미도 {ab.get("captivatingIndex")}',
          f'| 타구 {hit.get("launchSpeed")} mph, {hit.get("totalDistance")} ft' if hit.get("launchSpeed") else "")
    print("(③ 은 타자의 성이 들어간 문장을 찾은 것이라 다른 타석 이야기가 섞일 수 있습니다. 어느 문장이 이 타석 얘기인지 골라 보세요.)")

_three_registers(at_bat)
'''

CELL5 = '''#@title 5. 승리확률 그래프 { display-mode: "form" }
#@markdown 홈팀이 이길 확률이 타석마다 어떻게 움직였는지. 4번 셀의 타석이 점으로 찍힙니다.
import matplotlib.pyplot as plt

def _plot():
    if "feed" not in STATE:
        print("먼저 2번 셀을 실행하세요."); return
    if "winprob" not in STATE:
        STATE["winprob"] = {w["atBatIndex"]: w for w in get(f'v1/game/{STATE["game_pk"]}/winProbability')}
    wp = STATE["winprob"]
    xs = sorted(wp)
    ys = [wp[i]["homeTeamWinProbability"] for i in xs]
    gd = STATE["feed"]["gameData"]
    home, away = gd["teams"]["home"]["abbreviation"], gd["teams"]["away"]["abbreviation"]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(xs, ys, color="#1f4e79", linewidth=1.8)
    ax.axhline(50, color="#999", linewidth=0.8, linestyle="--")
    try:
        ab = globals()["at_bat"]  # 4번 셀의 타석 번호 (없으면 표시 안 함)
        ax.scatter([ab], [wp[ab]["homeTeamWinProbability"]], color="#d62828", zorder=5, s=60)
        ax.annotate(f"#{ab}", (ab, wp[ab]["homeTeamWinProbability"]), textcoords="offset points", xytext=(6, 6), color="#d62828")
    except KeyError:
        pass
    # 이닝 경계
    prev = None
    for p in STATE["plays"]:
        inn = p["about"]["inning"]
        if inn != prev:
            ax.axvline(p["about"]["atBatIndex"], color="#ddd", linewidth=0.6)
            ax.text(p["about"]["atBatIndex"] + 0.3, 97, str(inn), fontsize=8, color="#666")
            prev = inn
    ax.set_ylim(0, 100)
    ax.set_xlabel("plate appearance (at-bat index)")
    ax.set_ylabel(f"{home} win probability (%)")
    ax.set_title(f"{away} @ {home}  {gd['datetime']['officialDate']}")
    plt.tight_layout()
    plt.show()
    biggest = max(xs, key=lambda i: abs(wp[i].get("homeTeamWinProbabilityAdded") or 0))
    print(f"승률을 가장 많이 움직인 타석: #{biggest} ({wp[biggest]['homeTeamWinProbabilityAdded']:+.1f}%p, 홈팀 기준) — 2번 표에서 그 줄을 찾아보세요.")

_plot()
'''

CELL6 = '''#@title 6. 단어 찾기: 최근 며칠치 기사에서 { display-mode: "form" }
#@markdown 궁금한 단어를 넣고 ▶. 끝나는 날짜부터 거꾸로 며칠치 리캡 기사를 받아 그 단어가 든 문장을 모읍니다. (하루에 요청 1번)
word = "clutch" #@param {type:"string"}
end_date = "2026-09-17" #@param {type:"date"}
days = 7 #@param {type:"slider", min:1, max:14, step:1}

import datetime as dt
end = dt.date.fromisoformat(end_date)
pattern = re.compile(rf"\\b{re.escape(word.strip())}\\b", re.I)
rows, n_games, n_sent = [], 0, 0
for k in range(days):
    day = (end - dt.timedelta(days=k)).isoformat()
    sched = get("v1/schedule", sportId=1, date=day, hydrate="game(content(editorial(recap)))")
    for d in sched.get("dates", []):
        for g in d["games"]:
            rec = (((g.get("content") or {}).get("editorial") or {}).get("recap") or {}).get("mlb") or {}
            if not rec.get("body"):
                continue
            n_games += 1
            label = f'{g["teams"]["away"]["team"]["name"]} @ {g["teams"]["home"]["team"]["name"]}'
            _, paras = recap_paragraphs(rec["body"])
            for para in paras:
                for s in sentences(para):
                    n_sent += 1
                    if pattern.search(s):
                        rows.append({"날짜": day, "경기": label, "기사 제목": rec.get("headline", ""), "문장": s})
found = pd.DataFrame(rows)
print(f'{days}일치 기사 {n_games}편, 문장 {n_sent:,}개 중 "{word}" 가 든 문장 {len(found)}개')
if not found.empty:
    show(found)
'''


def build() -> nbformat.NotebookNode:
    nb = new_notebook()
    nb.metadata = {
        "colab": {"name": "mlb_playground.ipynb", "provenance": []},
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python"},
    }
    nb.cells = [
        new_markdown_cell(INTRO),
        new_code_cell(SETUP),
        new_code_cell(CELL1),
        new_code_cell(CELL2),
        new_code_cell(CELL3),
        new_code_cell(CELL4),
        new_code_cell(CELL5),
        new_code_cell(CELL6),
    ]
    for cell in nb.cells:
        if cell.cell_type == "code":
            cell.metadata["cellView"] = "form"
    return nb


if __name__ == "__main__":
    import pathlib

    out = pathlib.Path(__file__).with_name("mlb_playground.ipynb")
    nbformat.write(build(), out)
    print("wrote", out)
