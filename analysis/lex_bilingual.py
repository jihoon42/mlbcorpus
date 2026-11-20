#!/usr/bin/env python3
"""영어·스페인어 캡션의 대응과 시즌별 변화. 입력은 lex_network.py --step seqs 와 lex_units.py --lang es 의 출력.

같은 하이라이트 항목의 영어 캡션과 스페인어 캡션은 같은 타석을 가리킨다.
그래서 번역 사전 없이도 '같은 장면을 두 언어가 어떤 말로 적는가'를 셀 수 있다.

만드는 것 (data/tables/lex/)
  lead_es.csv            스페인어 캡션의 사건별 머리 표현 분포
  diversity_season.csv   시즌별 머리 동사의 유효 가짓수 (영어·스페인어, 표본 크기를 맞춘 값 포함)
  align_lead.csv         머리 동사 대응 (영어 ↔ 스페인어), 목적어 명사 대응
  align_units.csv        표현 단위 대응 (사전의 '다른 언어 대응 표현'에 쓴다)
  units_freq_es.csv      스페인어 표현 단위 빈도
  bilingual.json         요약 수치
"""
from __future__ import annotations

import json
import math
import pickle
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lexlib as X  # noqa: E402
import lex_network as NW  # noqa: E402

ES_FW = set("el la los las de del con para en por un una su al y se que lo le a".split())
EN_FW = set("the a an to in of and his for with on at by from as is".split())
WORD = re.compile(r"[a-záéíóúñü']+")
EVENTS = ["home_run", "single", "double", "triple", "strikeout", "walk", "field_out", "sac_fly",
          "grounded_into_double_play", "force_out", "field_error", "hit_by_pitch"]


def is_spanish(s) -> bool:
    if not isinstance(s, str):
        return False
    t = WORD.findall(s.lower())
    return sum(w in ES_FW for w in t) > sum(w in EN_FW for w in t) or (len(t) <= 6 and not any(w in EN_FW for w in t) and bool(t))


def lead_es(us, title=False):
    first = [u for u in us if u[2] < 1000]
    for u in first:
        if u[1] == "V":
            return u[0] + "|V"
    if title:
        ns = [u for u in first if u[1] == "N"]
        return ns[0][0] + "|N" if ns else None
    return None


def obj_es(us):
    first = [u for u in us if u[2] < 1000]
    for i, u in enumerate(first):
        if u[1] == "V":
            for x in first[i + 1:]:
                if x[2] - u[3] > 5:
                    return None
                if x[1] == "N":
                    return x[0] + "|N"
            return None
    return None


def eff_n(counter) -> float:
    tot = sum(counter.values())
    if not tot:
        return float("nan")
    ps = np.array([c / tot for c in counter.values()])
    return float(np.exp(-(ps * np.log(ps)).sum()))


def eff_sub(values, n=1500, reps=30, seed=11) -> float:
    """표본 크기를 n 으로 맞춘 유효 가짓수 (비복원 추출 평균). 시즌마다 건수가 달라도 비교할 수 있게."""
    if len(values) < n:
        return float("nan")
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=object)
    return float(np.mean([eff_n(Counter(rng.choice(arr, n, replace=False))) for _ in range(reps)]))


def main() -> int:
    root = "."
    out = X.lex_dir(root)
    with open(out / "seqs_en.pkl", "rb") as f:
        seqs_en, meta = pickle.load(f)
    NW.find_mwe(seqs_en)  # 저장된 영어 단위열은 묶기 전 상태라 여기서 다시 묶는다 (home run, grand slam ...)
    U = X.load_units(root, "es")
    cp = X.load_caps(root, ["game_pk", "season", "date", "guid", "at_bat_index", "linked_is_last", "event_type", "title_es_m", "desc_es_m"])
    lk = cp[cp.guid.notna() & cp.at_bat_index.notna() & (cp.date < X.HOLDOUT_FROM)].reset_index(drop=True)
    assert len(lk) == len(meta), (len(lk), len(meta))
    seqs_es = []
    for i, r in enumerate(lk.itertuples(index=False)):
        et = r.event_type if r.linked_is_last == 1 and isinstance(r.event_type, str) else ""
        if is_spanish(r.title_es_m):
            seqs_es.append(["capt", et, "", 1, X.text_units(r.title_es_m, U), i])
        if is_spanish(r.desc_es_m):
            seqs_es.append(["capd", et, "", 1, X.text_units(r.desc_es_m, U), i])
    es_fix = {"ponchaber": "ponchar", "ponchaberse": "poncharse", "remolcir": "remolcar", "sientar": "sentar", "jonron": "jonrón",
              "impulsir": "impulsar", "empujir": "empujar", "conectir": "conectar"}
    for q in seqs_es:  # 태거가 낸 잘못된 기본형 바로잡기
        for u in q[4]:
            if u[0] in es_fix:
                u[0] = es_fix[u[0]]
    mwe_es = NW.find_mwe(seqs_es)
    (out / "mwe_es.json").write_text(json.dumps(mwe_es, ensure_ascii=False), encoding="utf-8")
    season = lk.season.values

    en = {"capt": {}, "capd": {}}
    for reg, et, tr, w, us, rid in seqs_en:
        if reg in en and rid >= 0:
            en[reg][rid] = (et, us)
    es = {"capt": {}, "capd": {}}
    for reg, et, tr, w, us, rid in seqs_es:
        es[reg][rid] = (et, us)
    summary = {"rows": {"en_title": len(en["capt"]), "en_desc": len(en["capd"]), "es_title": len(es["capt"]), "es_desc": len(es["capd"]),
                        "pairs_title": len(set(en["capt"]) & set(es["capt"])), "pairs_desc": len(set(en["capd"]) & set(es["capd"]))},
               "mwe_es": len(mwe_es)}

    # ---- 스페인어 단위 빈도
    fq = Counter()
    for reg, et, tr, w, us, rid in seqs_es:
        for k in {u[0] + "|" + u[1] for u in us}:
            fq[(reg, k)] += 1
    rows = defaultdict(dict)
    for (reg, k), c in fq.items():
        rows[k][reg] = c
    pd.DataFrame([{"unit": k.rsplit("|", 1)[0], "cls": k.rsplit("|", 1)[1], "f_capt": v.get("capt", 0), "f_capd": v.get("capd", 0)}
                  for k, v in rows.items()]).sort_values("f_capd", ascending=False).to_csv(out / "units_freq_es.csv", index=False)
    summary["vocab_es"] = {"all": len(rows), "ge30": sum(1 for v in rows.values() if v.get("capt", 0) + v.get("capd", 0) >= 30)}

    # ---- 머리 표현 (언어 × 글 종류 × 사건)
    lead = {("en", "capd"): {}, ("es", "capd"): {}, ("en", "capt"): {}, ("es", "capt"): {}}
    obj = {"en": {}, "es": {}}
    for rid, (et, us) in en["capd"].items():
        lead[("en", "capd")][rid] = NW.lead_unit("capd", us)
        obj["en"][rid] = NW.object_noun(us)
    for rid, (et, us) in en["capt"].items():
        lead[("en", "capt")][rid] = NW.lead_unit("capt", us)
    for rid, (et, us) in es["capd"].items():
        lead[("es", "capd")][rid] = lead_es(us)
        obj["es"][rid] = obj_es(us)
    for rid, (et, us) in es["capt"].items():
        lead[("es", "capt")][rid] = lead_es(us, title=True)
    ev = {rid: et for d in (en["capt"], en["capd"], es["capt"], es["capd"]) for rid, (et, us) in d.items()}

    rows = []
    for (lang, reg), d in lead.items():
        by = defaultdict(Counter)
        for rid, l in d.items():
            if l and ev[rid]:
                by[ev[rid]][l] += 1
        for et, cnt in by.items():
            tot = sum(cnt.values())
            if tot >= 200:
                top = cnt.most_common(12)
                rows.append((lang, reg, et, tot, sum(1 for c in cnt.values() if c >= 5), round(eff_n(cnt), 2), round(top[0][1] / tot, 3),
                             "; ".join(f"{k.split('|')[0]} {c / tot:.1%}" for k, c in top)))
    lead_df = pd.DataFrame(rows, columns=["lang", "register", "event_type", "rows", "n_lead_ge5", "effective_n", "top1_share", "top12"])
    lead_df.sort_values(["event_type", "register", "lang"]).to_csv(out / "lead_es.csv", index=False)

    # ---- 목적어 명사의 분포 (언어 × 사건): 영어는 동사가, 스페인어는 명사가 다양한가
    rows = []
    for lang in ("en", "es"):
        by = defaultdict(Counter)
        for rid, o in obj[lang].items():
            if o and ev[rid]:
                by[ev[rid]][o] += 1
        for et, cnt in by.items():
            tot = sum(cnt.values())
            if tot >= 200:
                top = cnt.most_common(12)
                rows.append((lang, et, tot, sum(1 for c in cnt.values() if c >= 5), round(eff_n(cnt), 2), round(top[0][1] / tot, 3),
                             "; ".join(f"{k.split('|')[0]} {c / tot:.1%}" for k, c in top)))
    obj_df = pd.DataFrame(rows, columns=["lang", "event_type", "rows", "n_obj_ge5", "effective_n", "top1_share", "top12"])
    obj_df.sort_values(["event_type", "lang"]).to_csv(out / "obj_es.csv", index=False)

    # ---- 사건 전용 어휘: 그 사건에서 80% 이상 쓰이는 동사·명사가 언어별로 몇 가지인가 (문장 속 자리와 무관)
    rows = []
    spec = {}
    for lang, d in (("en", en["capd"]), ("es", es["capd"])):
        cnt = defaultdict(Counter)
        for rid, (et, us) in d.items():
            if et:
                for k in {u[0] + "|" + u[1] for u in us if u[1] in "VN"}:
                    cnt[k][et] += 1
        for et in ("home_run", "single", "double", "strikeout"):
            for cls in "VN":
                items = {k: c[et] for k, c in cnt.items() if k.endswith("|" + cls) and sum(c.values()) >= 30 and c[et] / sum(c.values()) >= 0.8}
                top = sorted(items.items(), key=lambda kv: -kv[1])[:14]
                rows.append((lang, et, cls, len(items), round(eff_n(Counter(items)), 2), "; ".join(f"{k.split('|')[0]} {c}" for k, c in top)))
                spec[(lang, et, cls)] = (len(items), round(eff_n(Counter(items)), 2))
    spec_df = pd.DataFrame(rows, columns=["lang", "event_type", "cls", "n_specific", "effective_n", "top"])
    spec_df.to_csv(out / "specific_vocab.csv", index=False)

    # ---- 시즌별 다양성 (캡션 설명의 머리 동사)
    rows = []
    for lang in ("en", "es"):
        d = lead[(lang, "capd")]
        for et in ("home_run", "single", "double", "strikeout", "field_out", "ALL"):
            for yr in sorted(set(season)):
                vals = [l for rid, l in d.items() if l and l.endswith("|V") and season[rid] == yr and (et == "ALL" and ev[rid] or ev[rid] == et)]
                if len(vals) < 300:
                    continue
                c = Counter(vals)
                rows.append((lang, et, int(yr), len(vals), round(eff_n(c), 2), round(eff_sub(vals), 2), len(c),
                             round(c.most_common(1)[0][1] / len(vals), 3), c.most_common(1)[0][0].split("|")[0]))
    div = pd.DataFrame(rows, columns=["lang", "event_type", "season", "n", "effective_n", "effective_n_at1500", "distinct", "top1_share", "top1"])
    div.to_csv(out / "diversity_season.csv", index=False)

    # ---- 머리 동사·목적어 명사 대응 (같은 항목의 영어 설명 ↔ 스페인어 설명)
    rows = []
    cond = {}
    for slot, a, b in (("V", lead[("en", "capd")], lead[("es", "capd")]), ("O", obj["en"], obj["es"]), ("T", lead[("en", "capt")], lead[("es", "capt")])):
        pair, fa, fb, n = Counter(), Counter(), Counter(), 0
        for rid in set(a) & set(b):
            x, y = a[rid], b[rid]
            if x and y:
                pair[(x, y)] += 1
                fa[x] += 1
                fb[y] += 1
                n += 1
        for (x, y), c in pair.items():
            if c >= 15:
                rows.append((slot, x, y, c, round(c / fa[x], 3), round(c / fb[y], 3), round(math.log2(c * n / (fa[x] * fb[y])), 2), fa[x], fb[y]))
        # 조건부 엔트로피: 한쪽 말을 알 때 다른 쪽 말이 얼마나 남는가
        h_ba = -sum(c / n * math.log2(c / fa[x]) for (x, y), c in pair.items())
        h_ab = -sum(c / n * math.log2(c / fb[y]) for (x, y), c in pair.items())
        cond[slot] = {"pairs": n, "eff_en": round(eff_n(fa), 2), "eff_es": round(eff_n(fb), 2), "H_es_given_en": round(h_ba, 3), "H_en_given_es": round(h_ab, 3),
                      "distinct_en": len(fa), "distinct_es": len(fb)}
    pd.DataFrame(rows, columns=["slot", "en", "es", "count", "p_es_given_en", "p_en_given_es", "pmi", "f_en", "f_es"]).sort_values(
        ["slot", "count"], ascending=[True, False]).to_csv(out / "align_lead.csv", index=False)
    summary["align"] = cond

    # ---- 표현 단위 대응 (같은 품사끼리. 점수 = P(es|en)·P(en|es))
    pair, fa, fb = Counter(), Counter(), Counter()
    for reg in ("capt", "capd"):
        for rid in set(en[reg]) & set(es[reg]):
            ue = {u[0] + "|" + u[1] for u in en[reg][rid][1]}
            us_ = {u[0] + "|" + u[1] for u in es[reg][rid][1]}
            for x in ue:
                fa[x] += 1
            for y in us_:
                fb[y] += 1
            for x in ue:
                cx = x[-1]
                for y in us_:
                    if y[-1] == cx:
                        pair[(x, y)] += 1
    rows = []
    for (x, y), c in pair.items():
        if c >= 20 and fa[x] >= 30 and fb[y] >= 30:
            rows.append((x, y, c, fa[x], fb[y], round(c / fa[x], 3), round(c / fb[y], 3), round(c * c / (fa[x] * fb[y]), 4)))
    al = pd.DataFrame(rows, columns=["en", "es", "count", "f_en", "f_es", "p_es_given_en", "p_en_given_es", "score"])
    al.sort_values(["en", "score"], ascending=[True, False]).to_csv(out / "align_units.csv", index=False)
    summary["align_units"] = {"pairs_ge20": len(al)}
    (out / "bilingual.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    pd.set_option("display.width", 240); pd.set_option("display.max_colwidth", 190)
    print(json.dumps(summary, ensure_ascii=False))
    piv = lead_df[(lead_df.register == "capd") & lead_df.event_type.isin(EVENTS)].pivot(index="event_type", columns="lang", values="effective_n")
    print(piv.reindex(EVENTS).to_string())
    print(div[div.event_type.isin(["home_run", "single", "ALL"])].pivot(index="season", columns=["lang", "event_type"], values="effective_n_at1500").to_string())
    print(spec_df.to_string(index=False))
    print(obj_df[obj_df.event_type.isin(EVENTS)].pivot(index="event_type", columns="lang", values="effective_n").reindex(EVENTS).to_string())
    for x in obj_df[obj_df.event_type.isin(["home_run", "single", "strikeout"])].itertuples():
        print("OBJ", x.event_type, x.lang, ":", x.top12)
    r = lead_df[(lead_df.lang == "es") & (lead_df.register == "capd") & (lead_df.event_type.isin(["home_run", "single", "strikeout", "field_out"]))]
    for x in r.itertuples():
        print("LEAD", x.event_type, "es:", x.top12)
    return 0


if __name__ == "__main__":
    sys.exit(main())
