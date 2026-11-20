#!/usr/bin/env python3
"""표현 사전(모델 파일) 만들기와 점검. 입력은 lex_network.py, lex_bilingual.py 의 출력과 lex_gloss_ko.tsv.

서비스는 이 파일 하나(web/lexicon.json)와 MLB Stats API 만으로 돈다. 기사나 캡션 원문은 넣지 않는다.
표현마다 담는 것: 빈도, 등급(배울 순서), 묶음(커뮤니티), 쓰이는 사건, 같이 쓰는 말(공출현 이웃),
바꿔 쓸 말(같은 사건 맥락의 같은 자리 표현), 다른 언어 대응 표현, 타구 수치, 한국어 뜻, 글에 나오는 꼴.

점검은 모델을 만들 때 쓰지 않은 2026-09-01 이후 경기로 한다 (data/tables/lex/lexicon_eval.json).
"""
from __future__ import annotations

import csv
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lexlib as X  # noqa: E402
import lex_network as NW  # noqa: E402
import lex_bilingual as LB  # noqa: E402

MIN_F = 30
ES_FIX = {"ponchaber": "ponchar", "ponchaberse": "poncharse", "remolcir": "remolcar", "sientar": "sentar", "jonron": "jonrón",
          "impulsir": "impulsar", "empujir": "empujar", "conectir": "conectar", "fallir": "fallar", "amplíar": "ampliar",
          "jardin": "jardín", "anotir": "anotar", "fuerzar": "forzar"}
# spaCy 가 야구 동사의 3인칭 현재형을 명사로 읽은 것(Soto remolca dos ...)과 품사를 잘못 붙인 것을 되돌린다.
# 규칙으로 후보를 뽑은 뒤 눈으로 확인한 것만 적었다. captura, marca, ayuda 처럼 명사로도 쓰는 말은 건드리지 않는다.
ES_MERGE = {
    "remolca|N": "remolcar|V", "remolca|V": "remolcar|V", "conecta|N": "conectar|V", "manda|N": "mandar|V", "anota|N": "anotar|V",
    "anote|N": "anotar|V", "logra|N": "lograr|V", "pega|N": "pegar|V", "empuja|N": "empujar|V", "empuja|M": "empujar|V",
    "lanza|N": "lanzar|V", "acerca|M": "acercar|V", "atrapa|N": "atrapar|V", "atrapa|V": "atrapar|V", "sella|N": "sellar|V",
    "sellan|V": "sellar|V", "empata|N": "empatar|V", "salva|N": "salvar|V", "salta|N": "saltar|V", "tira|N": "tirar|V",
    "tirándole|N": "tirar|V", "rebota|N": "rebotar|V", "bota|N": "botar|V", "escapa|N": "escapar|V", "pisa|N": "pisar|V",
    "corre|N": "correr|V", "fildea|N": "fildear|V", "fildea|M": "fildear|V", "vence|N": "vencer|V", "limpia|V": "limpiar|V",
    "gira|N": "girar|V", "pesca|N": "pescar|V", "fuerza|N": "forzar|V", "persigue|V": "perseguir|V", "enciende|V": "encender|V",
    "puede|V": "poder|V", "retiran|V": "retirar|V", "ventajar|V": "ventaja|N", "partir|V": "parte|N", "singlir|V": "single|N",
    "jonrón|V": "jonrón|N", "out|V": "out|N", "strikes|V": "strikes|N", "quieto|V": "quieto|M", "tremendo|V": "tremendo|M",
    "solo|V": "solo|M", "safe|V": "safe|M",
}
# 이름표가 벗겨지지 않은 이름, 자리표시자, 쪼개진 조각. 사전에는 넣지 않는다 (점검에서는 '모르는 말'로 센다).
DROP = {"en": {"'|N", "ji|N", "kiké|N", "vlad|N", "to-back|N", "hit away|V", "scoreless|V", "at|M"},
        "es": {"soto's|N", "soto's rbi|N", "a's|N", "ji|N", "ex|M", "home|V", "fans|V"}}
EVENT_KO = {
    "home_run": "홈런", "single": "단타", "double": "2루타", "triple": "3루타", "strikeout": "삼진", "walk": "볼넷",
    "intent_walk": "고의사구", "field_out": "범타", "sac_fly": "희생플라이", "sac_bunt": "희생번트",
    "grounded_into_double_play": "병살타", "double_play": "병살", "force_out": "포스아웃", "field_error": "실책 출루",
    "hit_by_pitch": "몸에 맞는 공", "fielders_choice": "야수 선택", "fielders_choice_out": "야수 선택 아웃",
    "strikeout_double_play": "삼진 병살", "caught_stealing_2b": "2루 도루 실패", "triple_play": "삼중살",
    "sac_fly_double_play": "희생플라이 병살", "catcher_interf": "타격 방해", "pickoff_1b": "1루 견제사",
}
GROUP_KO = {"bat": "타격·득점", "field": "수비", "pitch": "투구·마무리", "run": "주루·판정", "etc": "그 밖", "off": "기록 문장 용어"}


def es_seqs(root, U, holdout: bool):
    cp = X.load_caps(root, ["date", "guid", "at_bat_index", "linked_is_last", "event_type", "title_es_m", "desc_es_m"])
    m = cp.guid.notna() & cp.at_bat_index.notna() & ((cp.date >= X.HOLDOUT_FROM) if holdout else (cp.date < X.HOLDOUT_FROM))
    out = []
    for r in cp[m].itertuples(index=False):
        et = r.event_type if r.linked_is_last == 1 and isinstance(r.event_type, str) else ""
        for reg, txt in (("capt", r.title_es_m), ("capd", r.desc_es_m)):
            if LB.is_spanish(txt):
                us = X.text_units(txt, U)
                for u in us:
                    u[0] = ES_FIX.get(u[0], u[0])
                    k = ES_MERGE.get(u[0] + "|" + u[1])
                    if k:
                        u[0], u[1] = k.rsplit("|", 1)
                out.append([reg, et, "", 1, us, -1])
    return out


def en_holdout(root, U, score):
    cp = X.load_caps(root, ["date", "guid", "at_bat_index", "linked_is_last", "event_type", "title_en_m", "desc_en_m"])
    cp = cp[cp.guid.notna() & cp.at_bat_index.notna() & (cp.date >= X.HOLDOUT_FROM)]
    out = []
    for r in cp.itertuples(index=False):
        et = r.event_type if r.linked_is_last == 1 and isinstance(r.event_type, str) else ""
        for reg, txt in (("capt", r.title_en_m), ("capd", r.desc_en_m)):
            if isinstance(txt, str):
                out.append([reg, et, "", 1, X.apply_mwe(X.text_units(txt, U), score), -1])
    pl = X.load_plays(root, ["date", "event_type", "desc_en_m"])
    pl = pl[pl.date >= X.HOLDOUT_FROM]
    for (et, d), n in pl.groupby(["event_type", "desc_en_m"]).size().items():
        out.append(["off", et, "", int(n), X.apply_mwe(X.text_units(d, U), score), -1])
    return out, int(cp.shape[0]), int(pl.shape[0])


def tables(seqs):
    """단위별 빈도(글 종류별 행 수), 사건 분포, 글에 나온 꼴."""
    f = defaultdict(Counter)
    ev = defaultdict(Counter)
    forms = defaultdict(Counter)
    for reg, et, tr, w, us, rid in seqs:
        seen = set()
        for u in us:
            k = u[0] + "|" + u[1]
            if len(u) > 4:
                forms[k][u[4]] += w
            if k not in seen:
                seen.add(k)
                f[k][reg] += w
                if et:
                    ev[k][("off:" if reg == "off" else "cap:") + et] += w
    return f, ev, forms


def top_events(evc, prefix):
    c = {k[4:]: v for k, v in evc.items() if k.startswith(prefix)}
    tot = sum(c.values())
    return [[e, round(v / tot, 2)] for e, v in sorted(c.items(), key=lambda kv: -kv[1])[:3] if v / tot >= 0.08] if tot >= 20 else []


def coverage(seqs, known, regs):
    tot = hit = sent = sent_ok = 0
    for reg, et, tr, w, us, rid in seqs:
        if reg not in regs or not us:
            continue
        ks = [u[0] + "|" + u[1] for u in us]
        tot += w * len(ks)
        h = sum(k in known for k in ks)
        hit += w * h
        sent += w
        sent_ok += w * (h == len(ks))
    return (round(hit / tot, 4) if tot else None, round(sent_ok / sent, 4) if sent else None, tot)


def main() -> int:
    root = "."
    lex = X.lex_dir(root)
    with open(lex / "seqs_en.pkl", "rb") as fh:
        seqs_en, meta = pickle.load(fh)
    mwe_en = NW.find_mwe(seqs_en)
    score_en = {(x, y): s for x, y, s, c in mwe_en}
    U_en, U_es = X.load_units(root, "en"), X.load_units(root, "es")
    seqs_es = es_seqs(root, U_es, holdout=False)
    mwe_es = NW.find_mwe(seqs_es)
    score_es = {(x, y): s for x, y, s, c in mwe_es}

    gloss = {}
    with open(Path(__file__).resolve().parent / "lex_gloss_ko.tsv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            gloss[(r["lang"], r["unit"], r["cls"])] = r["ko"]

    def ko(lang, key):
        u, c = key.rsplit("|", 1)
        return gloss.get((lang, u, c)) or gloss.get((lang, u, "*"))

    # ------------------------------------------------ 영어
    f_en, ev_en, forms_en = tables(seqs_en)
    nodes = pd.read_csv(lex / "nodes_en.csv")
    nodes["key"] = nodes.unit + "|" + nodes.cls
    nd = nodes.set_index("key")
    summary = json.loads((lex / "net_en.json").read_text(encoding="utf-8"))
    arena = pd.DataFrame(summary["q1"]["table_arena"]).fillna(0)
    arena.index = arena.index.astype(int)
    big = nodes.comm_cap.dropna().astype(int).value_counts().index[:4].tolist()
    gname, left_ = {}, list(big)
    for label, col in (("pitch", "pitch"), ("bat", "bat"), ("field", "field")):
        c = max(left_, key=lambda k: arena.loc[k, col] if k in arena.index else 0)
        gname[c] = label
        left_.remove(c)
    gname[left_[0]] = "run"

    keys_en = [k for k, c in f_en.items() if sum(c.values()) >= MIN_F and k not in DROP["en"]]
    cap_f = {k: f_en[k]["capt"] + f_en[k]["capd"] for k in keys_en}
    co = defaultdict(list)
    for name in ("cooc_cap_en.csv", "cooc_off_en.csv"):
        e = pd.read_csv(lex / name)
        e = e[e["count"] >= 30].sort_values("npmi", ascending=False)
        for a, b, c, s in e.itertuples(index=False):
            for x, y in ((a, b), (b, a)):
                if len(co[x]) < 7 and y not in co[x]:
                    co[x].append(y)
    para = pd.read_csv(lex / "para_en.csv")
    para = para[para.cos >= 0.6].sort_values("f_b", ascending=False)
    alt = defaultdict(list)
    for slot, a, b, cos_, fa, fb in para.itertuples(index=False):
        if len(alt[a]) < 7 and b not in alt[a]:
            alt[a].append(b)
    # 다른 언어 대응: 같은 자리끼리(머리 동사 ↔ 머리 동사, 목적어 ↔ 목적어, 제목 머리 ↔ 제목 머리) 맞춘 쌍을 먼저 쓴다.
    # ventaja 처럼 어디에나 나오는 말이 끼지 않도록 우연보다 자주 만나는 쌍(PMI 0.2 이상)만 남긴다.
    x_en, x_es = defaultdict(dict), defaultdict(dict)
    ld = pd.read_csv(lex / "align_lead.csv")
    ld = ld[(ld["count"] >= 20) & (ld.en.str[-1] == ld.es.str[-1]) & ~ld.es.isin(["strikes|V", "swing|V", "out|V"])]
    ld = ld[((ld.en.str[-1] == "V") & (ld.pmi >= 0.2)) | ((ld.en.str[-1] != "V") & (ld.pmi >= 0.6))]
    # 순서는 '자주 만나는 정도 × 우연보다 얼마나 더 만나는가'. 흔한 대응(conectar)과 전용 대응(detonar)이 같이 올라온다.
    for r in ld.assign(k=ld.p_es_given_en * ld.pmi).sort_values("k", ascending=False).itertuples(index=False):
        if r.p_es_given_en >= 0.04 and len(x_en[r.en]) < 4:
            x_en[r.en].setdefault(r.es, round(r.p_es_given_en, 2))
    for r in ld.assign(k=ld.p_en_given_es * ld.pmi).sort_values("k", ascending=False).itertuples(index=False):
        if r.p_en_given_es >= 0.04 and len(x_es[r.es]) < 4:
            x_es[r.es].setdefault(r.en, round(r.p_en_given_es, 2))
    al = pd.read_csv(lex / "align_units.csv")
    al = al[(al["count"] >= 30) & (al.score >= 0.05)].sort_values("score", ascending=False)
    best_en, best_es = al.groupby("en").score.max(), al.groupby("es").score.max()
    for r in al.itertuples(index=False):  # 자리로 못 맞춘 말(꾸미는 말 등)은 문장 전체의 동시 등장으로 보충
        if r.en not in ld.en.values and r.score >= 0.5 * best_en[r.en] and len(x_en[r.en]) < 2:
            x_en[r.en].setdefault(r.es, round(r.p_es_given_en, 2))
        if r.es not in ld.es.values and r.score >= 0.5 * best_es[r.es] and len(x_es[r.es]) < 2:
            x_es[r.es].setdefault(r.en, round(r.p_en_given_es, 2))
    x_en = {k: [[a, b] for a, b in v.items()] for k, v in x_en.items()}
    x_es = {k: [[a, b] for a, b in v.items()] for k, v in x_es.items()}
    lr = pd.read_csv(lex / "lead_rows_en.csv.gz")
    base = lr.groupby("event_type")[["launch_speed", "launch_angle", "distance"]].mean()
    g = lr.groupby(["lead", "event_type"]).agg(n=("rid", "size"), s=("launch_speed", "mean"), a=("launch_angle", "mean"),
                                               d=("distance", "mean"), nd=("distance", "count")).reset_index()
    num = defaultdict(dict)
    for r in g[(g.n >= 100) & (g.nd >= 60) & g.event_type.isin(["home_run", "single", "double", "triple"])].itertuples(index=False):
        b = base.loc[r.event_type]
        num[r.lead][r.event_type] = [int(r.n), round(r.s, 1), round(r.a, 1), round(r.d), round(r.s - b.launch_speed, 1),
                                     round(r.a - b.launch_angle, 1), round(r.d - b.distance)]

    # ------------------------------------------------ 배울 순서: 빈도 대 중심성, 처음 보는 경기로 비교
    hold_en, n_cap_h, n_play_h = en_holdout(root, U_en, score_en)
    cap_keys = [k for k in keys_en if cap_f[k] > 0]
    orders = {
        "frequency": sorted(cap_keys, key=lambda k: -cap_f[k]),
        "strength": sorted(cap_keys, key=lambda k: -(nd.str_cap.get(k, 0) if pd.notna(nd.str_cap.get(k, np.nan)) else 0)),
        "kcore": sorted(cap_keys, key=lambda k: (-(nd.core_cap.get(k, 0) if pd.notna(nd.core_cap.get(k, np.nan)) else 0), -cap_f[k])),
    }
    curve = {name: {n: coverage(hold_en, set(o[:n]), {"capd"})[0] for n in (50, 100, 200, 400, 800)} for name, o in orders.items()}
    order = orders["frequency"]
    rank = {k: i for i, k in enumerate(order)}

    def tier(k):
        r = rank.get(k)
        if r is None:
            return 4
        return 1 if r < 100 else 2 if r < 300 else 3 if r < 700 else 4

    def same_event(a, b):  # 바꿔 쓸 말은 가장 흔한 사건이 같고, 둘 다 그 사건에 절반 이상 쓰일 때만
        ea, eb = top_events(ev_en[a], "cap:"), top_events(ev_en[b], "cap:")
        return bool(ea and eb and ea[0][0] == eb[0][0] and ea[0][1] >= 0.5 and eb[0][1] >= 0.5)

    en_units = {}
    for k in keys_en:
        u, c = k.rsplit("|", 1)
        cm = nd.comm_cap.get(k, np.nan)
        grp = gname.get(int(cm), "etc") if pd.notna(cm) else "off"
        rec = {"u": u, "c": c, "f": int(cap_f[k]), "fo": int(f_en[k]["off"]), "t": tier(k), "g": grp,
               "ev": top_events(ev_en[k], "cap:") or top_events(ev_en[k], "off:"),
               "co": [y for y in co.get(k, []) if y in f_en and sum(f_en[y].values()) >= MIN_F][:6],
               "alt": [y for y in alt.get(k, []) if y in f_en and sum(f_en[y].values()) >= MIN_F and (k.endswith("|V") or same_event(k, y))][:6],
               "x": x_en.get(k, []), "fm": [s for s, n in forms_en[k].most_common(5) if n >= 3]}
        if k in num:
            rec["num"] = num[k]
        if ko("en", k):
            rec["ko"] = ko("en", k)
        en_units[k] = rec

    # ------------------------------------------------ 스페인어
    f_es, ev_es, forms_es = tables(seqs_es)
    keys_es = [k for k, c in f_es.items() if sum(c.values()) >= MIN_F and k not in DROP["es"]]
    fq, nodes_es, edges_es, n_sent = NW.cooc_network(seqs_es, {"capt", "capd"})
    co_es = defaultdict(list)
    for a, b, c, s in sorted([e for e in edges_es if e[2] >= 30], key=lambda e: -e[3]):
        for x, y in ((a, b), (b, a)):
            if len(co_es[x]) < 6:
                co_es[x].append(y)
    order_es = sorted(keys_es, key=lambda k: -sum(f_es[k].values()))
    rank_es = {k: i for i, k in enumerate(order_es)}
    es_units = {}
    for k in keys_es:
        u, c = k.rsplit("|", 1)
        r = rank_es[k]
        rec = {"u": u, "c": c, "f": int(sum(f_es[k].values())), "t": 1 if r < 100 else 2 if r < 300 else 3 if r < 700 else 4,
               "ev": top_events(ev_es[k], "cap:"), "co": co_es.get(k, [])[:6], "x": x_es.get(k, []),
               "fm": [s for s, n in forms_es[k].most_common(5) if n >= 3]}
        if ko("es", k):
            rec["ko"] = ko("es", k)
        es_units[k] = rec

    def form_index(forms, units):
        idx = defaultdict(Counter)
        for k in units:
            for s, n in forms[k].items():
                if n >= 3:
                    idx[s][k] += n
        return {s: [k for k, n in c.most_common(3)] for s, c in idx.items()}

    # 합치거나 뺀 표현을 가리키던 연결을 정리한다.
    for v in en_units.values():
        v["co"] = [k for k in v["co"] if k in en_units]
        v["alt"] = [k for k in v["alt"] if k in en_units]
        xs = defaultdict(float)
        for k, p_ in v["x"]:
            xs[ES_MERGE.get(k, k)] += p_
        v["x"] = [[k, round(p_, 2)] for k, p_ in xs.items() if k in es_units]
    for v in es_units.values():
        v["co"] = [k for k in v["co"] if k in es_units]
        v["x"] = [[k, p_] for k, p_ in v["x"] if k in en_units]

    out = {
        "meta": {"built": "2026-11-20", "train_until": "2026-08-31", "min_freq": MIN_F,
                 "n_en": len(en_units), "n_es": len(es_units),
                 "glossed_en": sum("ko" in v for v in en_units.values()), "glossed_es": sum("ko" in v for v in es_units.values())},
        "groups": GROUP_KO, "events": EVENT_KO,
        "en": {"units": en_units, "forms": form_index(forms_en, en_units)},
        "es": {"units": es_units, "forms": form_index(forms_es, es_units)},
    }
    web = Path(root) / "web"
    web.mkdir(exist_ok=True)
    blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    (web / "lexicon.json").write_text(blob, encoding="utf-8")
    (web / "lexicon.js").write_text("window.LEXICON=" + blob + ";\n", encoding="utf-8")  # file:// 로 열어도 읽히게

    # ------------------------------------------------ 점검: 모델이 본 적 없는 2026년 9월 경기
    hold_es = [[r, e, t, w, X.apply_mwe(us, score_es), i] for r, e, t, w, us, i in es_seqs(root, U_es, holdout=True)]
    K_en, K_es = set(en_units), set(es_units)
    seen_en = set(f_en)
    ev_ = {"holdout": {"caption_rows": n_cap_h, "plays": n_play_h, "from": X.HOLDOUT_FROM},
           "lexicon": out["meta"],
           "recognition": {
               "en_caption_desc": coverage(hold_en, K_en, {"capd"}), "en_caption_title": coverage(hold_en, K_en, {"capt"}),
               "en_official": coverage(hold_en, K_en, {"off"}),
               "es_caption_desc": coverage(hold_es, K_es, {"capd"}), "es_caption_title": coverage(hold_es, K_es, {"capt"})},
           "glossed_token_share": {
               "en_caption_desc": coverage(hold_en, {k for k, v in en_units.items() if "ko" in v}, {"capd"})[0],
               "en_official": coverage(hold_en, {k for k, v in en_units.items() if "ko" in v}, {"off"})[0],
               "es_caption_desc": coverage(hold_es, {k for k, v in es_units.items() if "ko" in v}, {"capd"})[0]},
           "never_seen_token_share_en_desc": round(1 - coverage(hold_en, seen_en, {"capd"})[0], 4),
           "learning_order_coverage_en_desc": curve}
    (lex / "lexicon_eval.json").write_text(json.dumps(ev_, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(ev_, ensure_ascii=False))
    print("lexicon bytes", (web / "lexicon.json").stat().st_size, "| forms en/es", len(out["en"]["forms"]), len(out["es"]["forms"]))
    for k in ("crush|V", "home run|N", "strike out|V", "rip|V", "catch|N", "two-run|M"):
        v = en_units.get(k) or {}
        print(k, "| alt", v.get("alt"), "| x", v.get("x"))
    for k in ("conectar|V", "bambinazo|N", "ponchar|V", "jonrón|N", "remolcar|V"):
        v = es_units.get(k) or {}
        print(k, "| x", v.get("x"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
