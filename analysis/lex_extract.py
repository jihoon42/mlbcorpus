#!/usr/bin/env python3
"""표현 네트워크의 입력이 되는 문장 표를 원본에서 뽑는다.

경기 폴더(data/raw/games/{season}/{pk}/)마다
  winprob.json.gz          타석별 기록 문장, 사건 종류, 타구 수치, 승리확률 변화
  content.{en,es}.json.gz  하이라이트 캡션(제목·설명. guid 로 타석에 붙는다), 리캡 기사
를 읽어 data/tables/lex/ 아래에 조각 파일로 쓴다.

  plays.cNN.csv.gz     타석당 한 줄
  caps.cNN.csv.gz      하이라이트 항목당 한 줄 (영어·스페인어 나란히)
  recaps.cNN.jsonl.gz  경기·언어당 한 줄 (headline, 본문 텍스트)
  names.cNN.jsonl.gz   경기별 선수 이름 목록 (스페인어 기록 문장을 가릴 때 다시 쓴다)
  stats.cNN.json       조각별 집계

선수 이름은 <P>, 그 밖의 고유명사(팀, 구장, 도시)는 <N> 으로 가린 문장을 같이 쓴다.
표현 네트워크의 노드가 사람 이름으로 채워지지 않게 하기 위해서다.

사용 (한 번에 3분 안에 끝나도록 조각으로 나눠 돈다. 끝난 조각은 건너뛴다):
    python3 analysis/lex_extract.py --nchunks 16 --chunks 0,1,2,3 --procs 4
"""
from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import re
import sys
import time
import unicodedata
from multiprocessing import Pool
from pathlib import Path

try:  # orjson 이 있으면 3~5배 빠르다. 없으면 표준 json.
    import orjson

    loads = orjson.loads
except ImportError:  # pragma: no cover
    loads = json.loads

csv.field_size_limit(10**9)

SUFFIX = {"Jr.", "Jr", "Sr.", "Sr", "II", "III", "IV"}
PARTICLES = {"De", "La", "Del", "Los", "Las", "Van", "Von", "Da", "Di", "Le", "San", "Santa", "St"}
SENT_END = ".!?:"
TEAMS = ("Angels|Astros|Athletics|Blue Jays|Braves|Brewers|Cardinals|Cubs|D-backs|Diamondbacks|Dodgers|Giants|Guardians|"
         "Indians|Mariners|Marlins|Mets|Nationals|Orioles|Padres|Phillies|Pirates|Rangers|Rays|Red Sox|Reds|Rockies|"
         "Royals|Tigers|Twins|White Sox|Yankees")
TEAM_RX = re.compile(r"(?<![\w<])(?:" + TEAMS + r")(?![\w>])")
CAP_RX = re.compile(r"(?<![\w<])[A-Z](?=[A-Za-z'’\-]*[a-z])[A-Za-z]*(?:[-'’][A-Za-z]+)*(?![\w>])")
RUN_RX = re.compile(r"<[PN]>(?:(?:[ \-]+|, )?(?:de |del |la |los |las )?<[PN]>)+")

PLAY_COLS = [
    "game_pk", "season", "game_type", "date", "at_bat_index", "inning", "half", "event", "event_type",
    "desc_en", "desc_en_m", "batter_id", "pitcher_id", "rbi", "is_scoring", "is_out", "capt",
    "launch_speed", "launch_angle", "distance", "trajectory", "hardness", "location",
    "wpa_bat", "li", "bat_score_after", "fld_score_after", "n_caps",
]
CAP_COLS = [
    "game_pk", "season", "game_type", "date", "item_id", "guid", "at_bat_index", "linked_index", "linked_is_last",
    "linked_is_pitch", "linked_event", "linked_call", "event", "event_type",
    "title_en", "desc_en", "title_es", "desc_es", "title_en_m", "desc_en_m", "title_es_m", "desc_es_m",
    "taxonomy", "n_players",
]


CTRL_RX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def txt(v) -> str:
    """원본 문자열 정리. 일부 스페인어 제목에 NUL 문자가 섞여 있다 ('m\\x00ás')."""
    return CTRL_RX.sub("", v).strip() if isinstance(v, str) else ""


def load_gz(path: Path):
    with gzip.open(path, "rb") as f:
        return loads(f.read())


def strip_acc(s: str) -> str:
    """악센트를 떼되 글자 수는 그대로 둔다 (자리 계산을 원문에 그대로 쓰기 위해)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in s)


def name_variants(full: str) -> set[str]:
    parts = full.split()
    core = [p for p in parts if p not in SUFFIX]
    out = {full, " ".join(core)}
    if len(core) >= 2:
        last = " ".join(core[1:])
        out.add(last)
        if len(parts) != len(core):
            out.add(last + " " + parts[-1])
    if len(core) >= 3:  # "Ji Man Choi" 는 글에서 "Ji-Man Choi" 로도 나온다
        out.add(core[0] + "-" + core[1] + " " + " ".join(core[2:]))
    if "-" in full:
        out.add(full.replace("-", " "))
    return {v for v in out if v}


def build_masker(names, extra_tokens=()):
    variants, tokens = set(), set()
    for n in list(names) + list(extra_tokens):
        n = (n or "").strip()
        if not n:
            continue
        if n in names:
            for v in name_variants(n):
                variants.add(strip_acc(v))
        for t in n.split():
            t2 = strip_acc(t).strip(".,")
            if len(t2) >= 3 and t2[0].isupper() and t2 not in PARTICLES and t2 not in SUFFIX:
                tokens.add(t2)
                for sub in t2.split("-"):
                    if len(sub) >= 3 and sub[0].isupper():
                        tokens.add(sub)
    alts = sorted(variants, key=len, reverse=True)
    rx = re.compile(r"(?<![\w<])(?:" + "|".join(re.escape(a) for a in alts) + r")(?![\w>])") if alts else None
    return rx, tokens


def mask(text, rx, toks) -> str:
    if not text:
        return ""
    flat = strip_acc(text)
    spans = []
    covered = bytearray(len(flat))
    if rx is not None:
        for m in rx.finditer(flat):
            spans.append((m.start(), m.end(), "P"))
            for i in range(m.start(), m.end()):
                covered[i] = 1
    for m in TEAM_RX.finditer(flat):  # 팀 이름은 문장 첫머리에 와도 가린다 ("Dodgers challenged ...")
        if not covered[m.start()]:
            spans.append((m.start(), m.end(), "N"))
            for i in range(m.start(), m.end()):
                covered[i] = 1
    for m in CAP_RX.finditer(flat):
        a = m.start()
        if covered[a]:
            continue
        w = m.group(0)
        base = w[:-2] if w.endswith(("'s", "’s")) else w
        if len(base) == 1:  # K's (삼진), A's 같은 한 글자는 고유명사로 보지 않는다
            continue
        j = a - 1
        while j >= 0 and flat[j] in " \"'“‘(\n\t":
            j -= 1
        initial = j < 0 or flat[j] in SENT_END
        if base in toks:
            kind = "P"
        elif not initial:
            kind = "N"
        else:
            continue
        spans.append((a, a + len(base), kind))
    if not spans:
        return text
    spans.sort()
    out, pos = [], 0
    for a, b, k in spans:
        if a < pos:
            continue
        out.append(text[pos:a])
        out.append("<P>" if k == "P" else "<N>")
        pos = b
    out.append(text[pos:])
    s = "".join(out)
    return RUN_RX.sub(lambda m: "<P>" if "<P>" in m.group(0) else "<N>", s)


TAG_BLOCK = re.compile(r"<(iframe|script|blockquote|style|figure)\b.*?</\1>", re.S | re.I)
TAG_BR = re.compile(r"<br\s*/?>", re.I)
TAG_P = re.compile(r"</p\s*>|<p\b[^>]*>", re.I)
TAG_ANY = re.compile(r"<[^>]+>")
MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|/)[^)]*\)")


def clean_body(body: str) -> str:
    if not body:
        return ""
    s = TAG_BLOCK.sub(" ", body)
    s = TAG_BR.sub("\n", s)
    s = TAG_P.sub("\n\n", s)
    s = TAG_ANY.sub("", s)
    s = MD_LINK.sub(r"\1", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def load_schedule_meta(raw: Path) -> dict:
    meta = {}
    for fp in sorted((raw / "schedule").glob("*.json.gz")):
        d = load_gz(fp)
        for day in d.get("dates", []):
            for g in day.get("games", []):
                pk = g.get("gamePk")
                final = (g.get("status") or {}).get("detailedState") in ("Final", "Completed Early")
                if pk in meta and meta[pk]["final"] and not final:
                    continue
                t = g.get("teams") or {}
                meta[pk] = {
                    "final": final,
                    "date": g.get("officialDate") or day.get("date") or "",
                    "type": g.get("gameType") or "",
                    "home_id": ((t.get("home") or {}).get("team") or {}).get("id"),
                    "away_id": ((t.get("away") or {}).get("team") or {}).get("id"),
                }
    return meta


def items_of(content) -> list:
    return (((content.get("highlights") or {}).get("highlights") or {}).get("items")) or []


def process_game(season: int, pk: int, gdir: Path, gm: dict, w_play, w_cap, f_recap, f_names, st: dict) -> None:
    wp_path = gdir / "winprob.json.gz"
    if not wp_path.exists():
        st["no_winprob"] += 1
        return
    wp = load_gz(wp_path)
    names = set()
    for p in wp:
        mu = p.get("matchup") or {}
        for k in ("batter", "pitcher"):
            n = (mu.get(k) or {}).get("fullName")
            if n:
                names.add(n)
        for r in p.get("runners") or []:
            n = ((r.get("details") or {}).get("runner") or {}).get("fullName")
            if n:
                names.add(n)
    # 로스터의 이름 변이형까지 모아야 "Nicholas", "Ji-Man" 같은 표기가 남지 않는다
    extra = set()
    feed_path = gdir / "feed.json.gz"
    if feed_path.exists():
        try:
            players = (load_gz(feed_path).get("gameData") or {}).get("players") or {}
        except Exception:
            players = {}
        for pi in players.values():
            for k in ("fullName", "nameFirstLast", "firstLastName"):
                if pi.get(k):
                    names.add(pi[k])
            un, ul = pi.get("useName"), pi.get("useLastName") or pi.get("lastName")
            if un and ul:
                names.add(f"{un} {ul}")
            for k in ("firstName", "lastName", "useName", "useLastName"):
                if pi.get(k):
                    extra.add(pi[k])
    rx, toks = build_masker(names, extra)
    f_names.write(json.dumps({"pk": pk, "names": sorted(names)}, ensure_ascii=False) + "\n")

    gtype, date = gm.get("type", ""), gm.get("date", "")
    pid_map = {}
    play_info = {}
    rows = []
    for p in wp:
        about, res, mu = p.get("about") or {}, p.get("result") or {}, p.get("matchup") or {}
        abi = about.get("atBatIndex", p.get("atBatIndex"))
        hit = None
        last_pid = None
        for e in p.get("playEvents") or []:
            pid = e.get("playId")
            det = e.get("details") or {}
            if pid:
                pid_map[pid] = [abi, e.get("index"), 0, int(bool(e.get("isPitch"))), det.get("event") or "",
                                (det.get("call") or {}).get("description") or det.get("description") or ""]
                last_pid = pid
            if e.get("hitData"):
                hit = e["hitData"]
        if last_pid:
            pid_map[last_pid][2] = 1
        top = bool(about.get("isTopInning"))
        wpa = p.get("homeTeamWinProbabilityAdded")
        hs, as_ = res.get("homeScore"), res.get("awayScore")
        desc = txt(res.get("description"))
        play_info[abi] = (res.get("event") or "", res.get("eventType") or "")
        hit = hit or {}
        rows.append([
            pk, season, gtype, date, abi, about.get("inning"), "top" if top else "bottom",
            res.get("event") or "", res.get("eventType") or "", desc, mask(desc, rx, toks),
            (mu.get("batter") or {}).get("id"), (mu.get("pitcher") or {}).get("id"),
            res.get("rbi"), int(bool(about.get("isScoringPlay"))), int(bool(res.get("isOut"))),
            about.get("captivatingIndex"),
            hit.get("launchSpeed"), hit.get("launchAngle"), hit.get("totalDistance"),
            hit.get("trajectory") or "", hit.get("hardness") or "", hit.get("location") or "",
            (None if wpa is None else round((-wpa if top else wpa), 2)), p.get("leverageIndex"),
            (as_ if top else hs), (hs if top else as_), 0,
        ])
    st["plays"] += len(rows)

    # ---- 캡션
    en_path, es_path = gdir / "content.en.json.gz", gdir / "content.es.json.gz"
    en = load_gz(en_path) if en_path.exists() else {}
    es = load_gz(es_path) if es_path.exists() else {}
    es_by_id = {}
    for it in items_of(es):
        es_by_id.setdefault(it.get("id"), it)
    caps_per_play = {}
    for it in items_of(en):
        iid, guid = it.get("id") or "", it.get("guid") or ""
        e2 = es_by_id.get(iid) or {}
        link = pid_map.get(guid) if guid else None
        st["items"] += 1
        if guid:
            st["items_guid"] += 1
        if guid and link is None:
            st["guid_unmatched"] += 1
        if e2:
            st["items_es_pair"] += 1
        abi = link[0] if link else ""
        ev, evt = play_info.get(abi, ("", "")) if link else ("", "")
        t_en, d_en = txt(it.get("title")), txt(it.get("description"))
        t_es, d_es = txt(e2.get("title")), txt(e2.get("description"))
        if link:
            caps_per_play[abi] = caps_per_play.get(abi, 0) + 1
            if d_en:
                st["linked_desc_en"] += 1
            if d_es:
                st["linked_desc_es"] += 1
        kw = it.get("keywordsAll") or []
        tax = "|".join(k.get("value") or "" for k in kw if k.get("type") == "taxonomy")
        npl = sum(1 for k in kw if k.get("type") == "player_id")
        w_cap.writerow([
            pk, season, gtype, date, iid, guid, abi,
            link[1] if link else "", link[2] if link else "", link[3] if link else "",
            link[4] if link else "", link[5] if link else "", ev, evt,
            t_en, d_en, t_es, d_es, mask(t_en, rx, toks), mask(d_en, rx, toks), mask(t_es, rx, toks), mask(d_es, rx, toks),
            tax, npl,
        ])
    for r in rows:
        r[-1] = caps_per_play.get(r[4], 0)
        w_play.writerow(r)

    # ---- 리캡
    for lang, c in (("en", en), ("es", es)):
        rec = ((c.get("editorial") or {}).get("recap") or {}).get("mlb") or {}
        body = rec.get("body") or ""
        if not (rec.get("headline") or body):
            continue
        st["recap_" + lang] += 1
        f_recap.write(json.dumps({
            "pk": pk, "season": season, "type": gtype, "date": date, "lang": lang,
            "headline": txt(rec.get("headline")), "authors": [a.get("name") for a in rec.get("contributors") or []],
            "text": CTRL_RX.sub("", clean_body(body)),
        }, ensure_ascii=False) + "\n")
    st["games"] += 1


def run_chunk(args):
    root, out_dir, chunk, nchunks, force = args
    root, out_dir = Path(root), Path(out_dir)
    done = out_dir / f"stats.c{chunk:02d}.json"
    if done.exists() and not force:
        return chunk, "skip", 0.0
    raw = root / "data" / "raw"
    meta = load_schedule_meta(raw)
    games = []
    for sdir in sorted((raw / "games").iterdir()):
        if not sdir.name.isdigit():
            continue
        for gdir in sdir.iterdir():
            if gdir.name.isdigit():
                games.append((int(sdir.name), int(gdir.name), gdir))
    games.sort()
    mine = games[chunk::nchunks]
    st = {k: 0 for k in ("games", "plays", "items", "items_guid", "guid_unmatched", "items_es_pair",
                         "linked_desc_en", "linked_desc_es", "recap_en", "recap_es", "no_winprob", "errors")}
    t0 = time.time()
    tag = f"c{chunk:02d}"
    paths = {k: out_dir / f"{k}.{tag}.{ext}" for k, ext in
             (("plays", "csv.gz"), ("caps", "csv.gz"), ("recaps", "jsonl.gz"), ("names", "jsonl.gz"))}
    with gzip.open(paths["plays"], "wt", encoding="utf-8", newline="", compresslevel=5) as fp, \
         gzip.open(paths["caps"], "wt", encoding="utf-8", newline="", compresslevel=5) as fc, \
         gzip.open(paths["recaps"], "wt", encoding="utf-8", compresslevel=5) as fr, \
         gzip.open(paths["names"], "wt", encoding="utf-8", compresslevel=5) as fn:
        wp_, wc_ = csv.writer(fp), csv.writer(fc)
        wp_.writerow(PLAY_COLS)
        wc_.writerow(CAP_COLS)
        for season, pk, gdir in mine:
            try:
                process_game(season, pk, gdir, meta.get(pk, {}), wp_, wc_, fr, fn, st)
            except Exception as exc:  # 한 경기 때문에 조각 전체가 죽지 않게
                st["errors"] += 1
                sys.stderr.write(f"[{tag}] game {pk}: {type(exc).__name__}: {exc}\n")
    st["seconds"] = round(time.time() - t0, 1)
    st["n_assigned"] = len(mine)
    done.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return chunk, "done", st["seconds"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="data/tables/lex")
    ap.add_argument("--nchunks", type=int, default=16)
    ap.add_argument("--chunks", default="0,1,2,3")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="끝난 조각도 다시 만든다")
    a = ap.parse_args()
    out_dir = Path(a.root) / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = [int(x) for x in a.chunks.split(",") if x.strip() != ""]
    jobs = [(a.root, str(out_dir), c, a.nchunks, a.force) for c in chunks]
    with Pool(min(a.procs, len(jobs))) as pool:
        for chunk, status, sec in pool.imap_unordered(run_chunk, jobs):
            print(f"chunk {chunk:02d}: {status} ({sec}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
