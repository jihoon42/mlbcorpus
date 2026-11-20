#!/usr/bin/env python3
"""선수 사이의 관계 뽑기: 캡션에서 '누가 누구를 무엇했다'를 찾아 방향 있는 엣지로 만든다.

캡션에는 두 선수가 주어와 목적어로 함께 나오는 문장이 많다 (Justin Wrobleski fans Elly De La Cruz).
이름을 가린 글에서 '<P> 동사 <P>' 와 '<P> 동사 ... off/against <P>' 꼴을 찾고, 가리지 않은 글을 그 경기의
출전 명단과 맞대어 두 이름을 선수 번호로 바꾼다. 화살표는 주어에서 목적어로 간다.

이름을 잘못 맞춘 것을 걸러 내려고 동사 갈래마다 두 선수의 역할을 확인한다. 삼진과 범타 처리 동사는 그 타석의
투수가 주어, 타자가 목적어일 때만 받고, 타점 동사는 타자가 주어일 때만 받는다 (family 함수).

출력
  data/tables/lex/rel_rows.csv.gz   캡션 한 건당 한 줄 (주어, 목적어, 동사, 갈래, 타석). 문장은 없다
  data/tables/lex/rel_eval.json     건수와 판단 기준 수치
  web/relations.js                  서비스가 읽는 파일. 선수 이름, 동사, 횟수, 타석 번호만 있다

쓰는 법
  python3 analysis/lex_relations.py
  python3 analysis/lex_relations.py --only-game 824464 --out data/tables/lex/rel_fixture.js   # 점검용 한 경기
web/lexicon.json 의 '글에 나오는 꼴'로 동사의 기본형을 찾으므로 lex_lexicon.py 를 먼저 돌려 둔다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lexlib as X  # noqa: E402

STOP = {"and", "to", "or", "with", "vs", "at", "of", "in", "on", "for", "the", "a", "an", "is", "as", "from", "by"}
PA = r"^<P> ([A-Za-z']+(?: (?:out|off|down|away|up))?) <P>"           # X fans Y, X strikes out Y, X throws out Y
PB = r"^<P> ([A-Za-z']+)(?: [^.<]*?)? (off|against) (?:of )?<P>"      # X homers off Y
ES_A = r"^<P> (?:le |se )?([a-záéíóúñ]+) a <P>"                       # X poncha a Y (사람 목적어 앞의 a)

FAM_KO = {"k": "삼진", "out": "범타 처리", "run": "주루 저지", "def": "호수비", "rbi": "타점", "hit": "공략"}
FAM_OF = {
    "strike out": "k", "k": "k", "fan": "k", "freeze": "k", "whiff": "k", "punch out": "k", "sit down": "k", "ring": "k",
    "blow away": "k",
    "get": "out", "retire": "out", "force": "out", "induce": "out", "coax": "out", "set down": "out",
    "nab": "run", "throw out": "run", "catch": "run", "pick off": "run", "cut down": "run", "tag out": "run",
    "gun down": "run", "nail": "run", "double up": "run", "tag": "run", "erase": "run",
    "rob": "def", "field": "def", "snag": "def", "take away": "def", "deny": "def",
    "plate": "rbi", "score": "rbi", "drive in": "rbi", "drive home": "rbi", "bring home": "rbi", "bring in": "rbi",
    "knock in": "rbi", "send home": "rbi",
    "break up": "hit",
}
# off/against 앞에 와도 '공략'이 아닌 동사 (draws a walk against Y, ties the game off Y 따위)
DENY_OFF = {"draw", "tie", "win", "go", "work", "start", "lead", "collect", "break", "come", "open", "send", "extend", "get",
            "take", "bring", "help", "end", "secure", "reach", "leave", "face", "strike", "tally", "grab", "battle", "produce",
            "clear", "give", "put", "make", "field", "barehand"}


def family(label: str, sr: str, orr: str) -> str | None:
    """동사와 두 선수의 역할(P 그 타석의 투수, B 타자, O 그 밖의 선수)로 갈래를 정한다. 맞지 않으면 None."""
    if label.endswith(")"):                       # hit (off), crush (against): 타자가 투수를 공략
        return "hit" if (sr == "B" and orr == "P") else None
    f = FAM_OF.get(label)
    if f in ("k", "out"):
        return f if (sr == "P" and orr == "B") else None
    if f == "run":                                # 야수나 투수가 주자를 잡는다. catch 는 주자를 잡을 때만 (타구를 잡는 catch 는 뺀다)
        if label == "catch" and orr == "B":
            return None
        return f if sr != "B" else None
    if f == "def":                                # 야수가 타자의 타구를 처리한다
        return f if (sr != "B" and orr == "B") else None
    if f == "rbi":                                # 타자가 주자를 불러들인다
        return f if (sr == "B" and orr == "O") else None
    if f == "hit":
        return f if (sr == "B" and orr == "P") else None
    return None


def find_players(text: str, players) -> list[tuple[int, int, int]]:
    """글에 나온 선수를 (시작 자리, 끝 자리, 선수 번호)로 돌려준다.

    성명 전체를 먼저 찾고, 그 자리를 뺀 나머지에서만 성을 찾는다. Raisel Iglesias 의 Iglesias 를 같은 경기의
    Jose Iglesias 로 읽는 일을 막기 위해서다. 성이 같은 선수가 둘 남아 있으면 그 성은 쓰지 않는다.
    """
    hits, used = [], []
    for pid, fn, ln in players:
        if isinstance(fn, str) and fn:
            i = text.find(fn)
            if i >= 0:
                hits.append((i, i + len(fn), pid))
                used.append((i, i + len(fn)))
    found = {h[2] for h in hits}
    lasts = Counter(ln for pid, fn, ln in players if pid not in found and isinstance(ln, str))
    for pid, fn, ln in players:
        if pid in found or not isinstance(ln, str) or len(ln) < 3 or lasts[ln] != 1:
            continue
        j = text.find(ln)
        while j >= 0:
            end = j + len(ln)
            inside = any(a <= j < b for a, b in used)
            if not inside and (j == 0 or not text[j - 1].isalpha()) and not text[end:end + 1].isalpha():
                hits.append((j, end, pid))
                break
            j = text.find(ln, j + 1)
    hits.sort()
    return hits


def main() -> int:
    import pandas as pd

    ap = argparse.ArgumentParser(description="캡션에서 선수 사이의 관계를 뽑는다")
    ap.add_argument("--only-game", type=int, default=0, help="점검용: 이 경기만 뽑는다 (날짜 제한 없이)")
    ap.add_argument("--out", default="web/relations.js")
    ap.add_argument("--min-deg", type=int, default=10, help="화살표가 이만큼은 있어야 가운데에 설 수 있다")
    ap.add_argument("--per-side", type=int, default=6, help="한 선수의 들어오는 쪽과 나가는 쪽에 각각 담을 화살표 수")
    a = ap.parse_args()
    root = "."
    lex = X.lex_dir(root)
    full = not a.only_game
    min_deg = a.min_deg if full else 1

    cols = ["game_pk", "season", "date", "guid", "at_bat_index", "title_en", "desc_en", "title_en_m", "desc_en_m", "title_es_m", "desc_es_m"]
    cp = X.load_caps(root, cols)
    cp = cp[cp.guid.notna() & cp.at_bat_index.notna()]
    cp = (cp[cp.date < X.HOLDOUT_FROM] if full else cp[cp.game_pk == a.only_game]).copy()
    cp["at_bat_index"] = cp.at_bat_index.astype(int)

    parts = []
    for pri, (c, raw) in enumerate((("title_en_m", "title_en"), ("desc_en_m", "desc_en"))):   # 제목을 먼저 쓴다
        d = cp[c].str.extract(PA)[0].str.lower()
        d = d[~d.isin(STOP)].reindex(cp.index)
        b = cp[c].str.extract(PB)
        off = (b[0].str.lower() + " " + b[1]).where(d.isna())
        for v, kind in ((d, "direct"), (off, "off")):
            m = v.notna()
            t = cp.loc[m, ["game_pk", "season", "date", "guid", "at_bat_index", raw]].rename(columns={raw: "text"})
            t["surface"], t["kind"], t["pri"] = v[m], kind, pri
            parts.append(t)
    r = pd.concat(parts, ignore_index=True).sort_values("pri").drop_duplicates(["game_pk", "at_bat_index", "kind"], keep="first")

    pl = X.load_plays(root, ["game_pk", "at_bat_index", "batter_id", "pitcher_id"])
    r = r.merge(pl, on=["game_pk", "at_bat_index"], how="left")
    pg = pd.read_csv(Path(root) / "data/tables/player_game.csv.gz", usecols=["game_pk", "player_id", "full_name", "last_name"])
    pg = pg[pg.game_pk.isin(set(r.game_pk))]
    roster = defaultdict(list)
    for g, pid, fn, ln in zip(pg.game_pk, pg.player_id, pg.full_name, pg.last_name):
        roster[g].append((int(pid), fn, ln))
    names = pg.groupby("player_id").full_name.last().to_dict()

    lexicon = json.loads((Path(root) / "web/lexicon.json").read_text(encoding="utf-8"))
    forms, units = lexicon["en"]["forms"], lexicon["en"]["units"]

    def lemma(surface: str) -> str | None:        # strikes out → strike out, fans → fan, k's → k
        for cand in (surface, surface.split()[0]):
            ks = [k for k in forms.get(cand, []) if k.endswith("|V")]
            if ks:
                return ks[0][:-2]
        return None

    rows, why, unassigned, roles, n_both = [], Counter(), Counter(), Counter(), 0
    for t in r.itertuples(index=False):
        if not isinstance(t.text, str):
            why["글 없음"] += 1
            continue
        hits = find_players(t.text, roster.get(t.game_pk, ()))
        if not hits or hits[0][0] > 1:
            why["주어를 못 찾음"] += 1
            continue
        s = hits[0]
        o = next((h for h in hits[1:] if h[2] != s[2] and h[0] >= s[1]), None)
        if o is None:
            why["목적어를 못 찾음"] += 1
            continue
        n_both += 1
        if t.kind == "direct":
            label = lemma(t.surface)
        else:
            base, prep = t.surface.rsplit(" ", 1)
            lem = lemma(base)
            if lem in DENY_OFF:
                why["off/against 앞이 치는 동사가 아님"] += 1
                continue
            label = f"{lem} ({prep})" if lem else None
        if not label:
            why["사전에 없는 동사"] += 1
            continue
        role = lambda pid: "P" if pid == t.pitcher_id else "B" if pid == t.batter_id else "O"   # noqa: E731
        sr, orr = role(s[2]), role(o[2])
        roles[sr + ">" + orr] += 1
        fam = family(label, sr, orr)
        if not fam:
            why["관계 동사가 아니거나 역할이 맞지 않음"] += 1
            unassigned[f"{label} {sr}>{orr}"] += 1
            continue
        rows.append((s[2], o[2], label, fam, t.surface, sr, orr, int(t.game_pk), int(t.at_bat_index), t.guid, t.date, int(t.season)))
    e = pd.DataFrame(rows, columns=["s", "o", "label", "fam", "surface", "sr", "orr", "pk", "abi", "guid", "date", "season"]).sort_values("date")
    if e.empty:
        print("관계 캡션이 없습니다")
        return 1

    vc = e.label.value_counts()
    deg = pd.concat([e.s, e.o]).value_counts()
    pairs = e.groupby(["s", "o"]).size()
    non_k = e[e.fam != "k"].label.value_counts()

    # ------------------------------------------------ 서비스가 읽는 파일
    labels = list(vc.index)
    vid = {l: i for i, l in enumerate(labels)}
    s3 = e.groupby("label").surface.agg(lambda s: s.value_counts().index[0]).to_dict()      # 가장 흔한 꼴 = 3인칭 현재형
    fam_of = e.groupby("label").fam.first().to_dict()

    def shown(label: str) -> str:
        x = s3[label]
        return "K's" + x[3:] if x.startswith("k's") else x

    verbs = [[l, shown(l), (l.split(" (")[0] + "|V") if (l.split(" (")[0] + "|V") in units else None, fam_of[l], int(vc[l])] for l in labels]
    by_s, by_o = defaultdict(list), defaultdict(list)
    for t in e.itertuples(index=False):
        by_s[t.s].append(t)
        by_o[t.o].append(t)

    def pick(rs, other_of):
        """한 선수의 한쪽 화살표 고르기. 같은 상대와 같은 동사는 하나로 모으고, 갈래가 고루 섞이게 돌아가며 뽑는다."""
        agg = {}
        for t in rs:                              # 날짜순으로 돌므로 마지막에 남는 것이 가장 최근 타석
            k = (other_of(t), t.label)
            agg[k] = (agg[k][0] + 1 if k in agg else 1, t)
        cand = defaultdict(list)
        for i, ((other, label), (n, t)) in enumerate(agg.items()):
            cand[t.fam].append((-n, -int(deg.get(other, 0)), -int(t.date.replace("-", "")), i, other, label, n, t))
        for f in cand:
            cand[f].sort()
        order = sorted(cand, key=lambda f: -sum(x[6] for x in cand[f]))
        out = []
        while len(out) < a.per_side and any(cand[f] for f in order):
            for f in order:
                if cand[f] and len(out) < a.per_side:
                    *_, other, label, n, t = cand[f].pop(0)
                    out.append([int(other), vid[label], int(n), int(t.pk), int(t.abi), t.guid[:8]])
        return out

    ent = {}
    for pid, d in deg.items():
        if d < min_deg:
            continue
        outs, ins = by_s.get(pid, []), by_o.get(pid, [])
        ent[str(int(pid))] = {
            "no": len(outs), "ni": len(ins),
            "o": [[vid[l], int(n)] for l, n in Counter(t.label for t in outs).most_common(6)],
            "i": [[vid[l], int(n)] for l, n in Counter(t.label for t in ins).most_common(6)],
            "oe": pick(outs, lambda t: t.o), "ie": pick(ins, lambda t: t.s)}
    used = set(ent) | {str(x[0]) for v in ent.values() for x in v["oe"] + v["ie"]}
    out = {
        "meta": {"built": datetime.date.today().isoformat(), "train_until": "2026-08-31" if full else "", "captions": int(len(e)),
                 "pairs": int(len(pairs)), "players": int(deg.size), "centers": len(ent)},
        "fam": FAM_KO, "verbs": verbs,
        "names": {k: names.get(int(k), "?") for k in sorted(used)},
        "p": ent,
    }
    blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    dst = Path(root) / a.out
    dst.write_text("window.RELATIONS=" + blob + ";\n", encoding="utf-8")

    summary = {
        "linked_captions": int(len(cp)), "pattern_rows": int(len(r)), "both_players_found": int(n_both), "kept": int(len(e)),
        "dropped": dict(why), "roles_before_filter": dict(roles.most_common()), "unassigned_top": unassigned.most_common(20),
        "by_family": {FAM_KO[k]: int(v) for k, v in e.fam.value_counts().items()},
        "verbs": {l: int(n) for l, n in vc.head(40).items()},
        "criteria": {"kept_relation_captions": int(len(e)), "non_strikeout_verbs_100plus": int((non_k >= 100).sum()),
                     "strikeout_share": round(float((e.fam == "k").mean()), 3)},
        "graph": {"directed_pairs": int(len(pairs)), "players": int(deg.size), "pairs_2plus": int((pairs >= 2).sum()),
                  "pairs_3plus": int((pairs >= 3).sum()), "players_10plus_edges": int((deg >= 10).sum())},
        "by_season": {int(k): int(v) for k, v in e.season.value_counts().sort_index().items()},
        "file": {"path": str(a.out), "kb": round(len(blob.encode("utf-8")) / 1024), "centers": len(ent), "names": len(used)},
    }
    if full:
        e.drop(columns=["surface"]).to_csv(lex / "rel_rows.csv.gz", index=False)
        es = {c: {k: int(v) for k, v in cp[c].str.extract(ES_A)[0].value_counts().head(12).items()} for c in ("title_es_m", "desc_es_m")}
        summary["es_personal_a"] = {"title": int(cp.title_es_m.str.extract(ES_A)[0].notna().sum()), "desc": int(cp.desc_es_m.str.extract(ES_A)[0].notna().sum()), "top": es}
        (lex / "rel_eval.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("pattern_rows", "both_players_found", "kept", "dropped", "by_family", "criteria", "graph", "file")}, ensure_ascii=False))
    print("unassigned:", " | ".join(f"{k} {n}" for k, n in unassigned.most_common(14)))
    top = pairs.sort_values(ascending=False).head(6)
    print("top pairs:", "; ".join(f"{names.get(s)} > {names.get(o)} {n}" for (s, o), n in top.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
