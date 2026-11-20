#!/usr/bin/env python3
"""표현 네트워크 (영어). 입력은 lex_extract.py 와 lex_units.py 의 출력.

세 가지 글을 같은 노드(표현 단위)로 읽는다.
  off   기록 문장      "<P> homers (16) on a fly ball to right center field."
  capt  캡션 제목      "<P>'s two-run home run (16)"
  capd  캡션 설명      "<P> hammers a two-run home run to right-center field, ..."

만드는 것 (data/tables/lex/)
  mwe_en.json          한 단위로 묶은 두 단어 표현 (home run, line drive ...)
  nodes_en.csv         노드별 빈도, 사건 분포, 중심성, 커뮤니티
  cooc_{reg}_en.csv    공출현 네트워크의 엣지 (같은 문장에 함께 나온 표현. 통합 관계)
  bip_en.csv           사건–표현 이분 네트워크의 엣지
  lead_en.csv          사건별 '머리 표현'(문장의 첫 동사) 분포. 기의 하나당 기표 수
  para_en.csv          같은 사건 맥락을 가리키는 표현끼리의 엣지 (계열 관계)
  nuance_en.csv        머리 동사별 타구 수치 (같은 홈런·안타라도 동사에 따라 타구가 다른가)
  net_en.json          요약 수치
  net_cap_en.gexf      Gephi 등에서 열 수 있는 네트워크 파일

2026-09-01 이후 경기는 여기서 쓰지 않는다 (모델 점검용으로 남겨 둔다).

사용:  python3 analysis/lex_network.py --step seqs      (1분 안쪽)
       python3 analysis/lex_network.py --step net       (2분 안쪽)
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lexlib as X  # noqa: E402

MWE_MIN_COUNT, MWE_MIN_NPMI, MWE_MIN_SHARE = 50, 0.55, 0.6
MWE_LEFT_STOP = {"rbi"}
NODE_MIN = 30          # 네트워크에 넣는 최소 빈도 (그 글 종류 안에서)
EDGE_MIN_COUNT = 15
EDGE_MIN_NPMI = 0.05
BAT_TRAJ = {"fly_ball": "fly", "line_drive": "line", "ground_ball": "ground", "popup": "pop",
            "bunt_grounder": "bunt", "bunt_popup": "bunt", "bunt_line_drive": "bunt"}


def build_seqs(root: str):
    U = X.load_units(root, "en")
    cp = X.load_caps(root, ["game_pk", "season", "date", "guid", "at_bat_index", "linked_is_last", "event_type",
                            "title_en_m", "desc_en_m"])
    lk = cp[cp.guid.notna() & cp.at_bat_index.notna() & (cp.date < X.HOLDOUT_FROM)].copy()
    lk["at_bat_index"] = lk.at_bat_index.astype(int)
    pl = X.load_plays(root, ["game_pk", "date", "at_bat_index", "event_type", "desc_en_m", "launch_speed", "launch_angle",
                             "distance", "trajectory", "rbi", "wpa_bat", "li"])
    pl = pl[pl.date < X.HOLDOUT_FROM]
    pl["traj"] = pl.trajectory.map(BAT_TRAJ).fillna("")
    lk = lk.merge(pl[["game_pk", "at_bat_index", "launch_speed", "launch_angle", "distance", "traj", "rbi", "wpa_bat", "li"]],
                  on=["game_pk", "at_bat_index"], how="left")
    off = pl.groupby(["event_type", "traj", "desc_en_m"]).size().reset_index(name="n")
    seqs = []  # [register, event_type, traj, weight, units, row_id]
    for et, tr, d, n in off.itertuples(index=False):
        seqs.append(["off", et, tr, int(n), X.text_units(d, U), -1])
    for i, r in enumerate(lk.itertuples(index=False)):
        et = r.event_type if r.linked_is_last == 1 and isinstance(r.event_type, str) else ""
        tr = r.traj if isinstance(r.traj, str) else ""
        if isinstance(r.title_en_m, str):
            seqs.append(["capt", et, tr, 1, X.text_units(r.title_en_m, U), i])
        if isinstance(r.desc_en_m, str):
            seqs.append(["capd", et, tr, 1, X.text_units(r.desc_en_m, U), i])
    meta = lk[["game_pk", "season", "at_bat_index", "event_type", "linked_is_last", "launch_speed", "launch_angle",
               "distance", "traj", "rbi", "wpa_bat", "li"]].reset_index(drop=True)
    return seqs, meta


def find_mwe(seqs):
    """붙어 있는 두 단위 가운데 '거의 늘 같이 다니는' 쌍을 한 단위로 묶는다. 두 번 돌려 세 단어 표현까지 잡는다."""
    merged_all = []
    for _ in range(2):
        uni, bi, n_tok = Counter(), Counter(), 0
        for reg, et, tr, w, us, rid in seqs:
            for u in us:
                uni[u[0]] += w
            n_tok += w * len(us)
            for a, b in zip(us, us[1:]):
                if a[3] + 1 == b[2] and a[1] in "NM" and b[1] in "NM":
                    bi[(a[0], b[0])] += w
        score = {}
        for (x, y), c in bi.items():
            if c < MWE_MIN_COUNT or x in MWE_LEFT_STOP or ("-" in x and " " not in x):
                continue
            s = X.npmi(c, uni[x], uni[y], n_tok)
            if s >= MWE_MIN_NPMI and max(c / uni[x], c / uni[y]) >= MWE_MIN_SHARE:
                score[(x, y)] = s
        if not score:
            break
        for q in seqs:
            us = q[4]
            while True:  # 문장 안에서 점수가 가장 높은 쌍부터 묶는다 (sharp line drive → sharp + "line drive")
                best, bi_ = None, -1
                for i in range(len(us) - 1):
                    a, b = us[i], us[i + 1]
                    s = score.get((a[0], b[0]))
                    if s is not None and a[3] + 1 == b[2] and (best is None or s > best):
                        best, bi_ = s, i
                if best is None:
                    break
                a, b = us[bi_], us[bi_ + 1]
                new = [a[0] + " " + b[0], "N" if b[1] == "N" else b[1], a[2], b[3]]
                if len(a) > 4 and len(b) > 4:
                    new.append(a[4] + " " + b[4])  # 글에 나온 꼴도 이어 붙인다
                us[bi_:bi_ + 2] = [new]
            q[4] = us
        merged_all.extend(sorted(((x, y, round(s, 3), bi[(x, y)]) for (x, y), s in score.items()), key=lambda r: -r[3]))
    return merged_all


REVIEW = {"challenge", "review", "call", "overturn", "confirm", "uphold", "stand", "tag play", "pitch result",
          "original call", "field", "umpire", "stadium boundary", "boundary call"}
ARENA = {"single": "bat", "double": "bat", "triple": "bat", "home_run": "bat", "walk": "bat", "intent_walk": "bat",
         "hit_by_pitch": "bat", "sac_fly": "bat", "sac_bunt": "bat", "field_error": "bat", "fielders_choice": "bat",
         "strikeout": "pitch", "strikeout_double_play": "pitch",
         "field_out": "field", "force_out": "field", "grounded_into_double_play": "field", "double_play": "field",
         "fielders_choice_out": "field", "triple_play": "field", "sac_fly_double_play": "field"}


def first_run(us: list) -> list:
    """맨 앞에서부터 '바로 붙어 있는' 단위들. 전치사 같은 빠진 말이 나오면 끊긴다."""
    run = []
    for u in us:
        if run and u[2] != run[-1][3] + 1:
            break
        run.append(u)
    return run


def lead_unit(reg: str, us: list) -> str | None:
    """머리 표현: 첫 문장의 첫 동사. 판정 번복 문구(challenged ... overturned:)는 건너뛴다.
    제목처럼 동사가 없으면 맨 앞 명사구의 머리 명사 ("<P>'s 30th home run of the season" → home run)."""
    first = [u for u in us if u[2] < 1000]
    if reg == "off":
        first = [u for u in first if u[0] not in REVIEW]
    for u in first:
        if u[1] == "V":
            return u[0] + "|V"
    if reg == "capt":
        ns = [u for u in first_run(first) if u[1] == "N"]
        if ns:
            return ns[-1][0] + "|N"
    elif first:
        return first[0][0] + "|" + first[0][1]
    return None


def object_noun(us: list) -> str | None:
    """머리 동사의 목적어 자리 명사: 동사 뒤 세 토큰 안에서 시작하는 첫 명사구의 머리 ("crushes a two-run home run" → home run)."""
    first = [u for u in us if u[2] < 1000]
    for i, u in enumerate(first):
        if u[1] == "V":
            rest = [x for x in first[i + 1:]]
            if not rest or rest[0][2] - u[3] > 4:
                return None
            ns = [x for x in first_run(rest) if x[1] == "N"]
            return ns[-1][0] + "|N" if ns else None
    return None


def cooc_network(seqs, regs, node_min=NODE_MIN):
    freq, pair, n_sent = Counter(), Counter(), 0
    for reg, et, tr, w, us, rid in seqs:
        if reg not in regs:
            continue
        by_sent = defaultdict(set)
        for u in us:
            by_sent[u[2] // 1000].add(u[0] + "|" + u[1])
        for s in by_sent.values():
            n_sent += w
            ks = sorted(s)
            for k in ks:
                freq[k] += w
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    pair[(ks[i], ks[j])] += w
    nodes = {k for k, c in freq.items() if c >= node_min}
    edges = []
    for (a, b), c in pair.items():
        if c >= EDGE_MIN_COUNT and a in nodes and b in nodes:
            s = X.npmi(c, freq[a], freq[b], n_sent)
            if s >= EDGE_MIN_NPMI:
                edges.append((a, b, c, round(s, 4)))
    return freq, nodes, edges, n_sent


def graph_stats(nodes, edges, seed=7):
    import networkx as nx
    import community as louvain

    G = nx.Graph()
    G.add_nodes_from(nodes)
    for a, b, c, s in edges:
        G.add_edge(a, b, weight=s, count=c)
    iso = [n for n in G if G.degree(n) == 0]
    G.remove_nodes_from(iso)
    giant = G.subgraph(max(nx.connected_components(G), key=len)).copy()
    part = louvain.best_partition(giant, weight="weight", random_state=seed)
    mod = louvain.modularity(part, giant, weight="weight")
    deg = dict(giant.degree())
    strength = dict(giant.degree(weight="weight"))
    core = nx.core_number(giant)
    btw = nx.betweenness_centrality(giant, k=min(400, giant.number_of_nodes()), seed=seed)
    stats = {
        "nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "isolated_dropped": len(iso),
        "giant_nodes": giant.number_of_nodes(), "giant_edges": giant.number_of_edges(),
        "density": round(nx.density(giant), 5), "avg_degree": round(2 * giant.number_of_edges() / giant.number_of_nodes(), 2),
        "avg_clustering": round(nx.average_clustering(giant), 4),
        "transitivity": round(nx.transitivity(giant), 4),
        "communities": len(set(part.values())), "modularity": round(mod, 4), "max_core": max(core.values()),
    }
    return giant, part, deg, strength, core, btw, stats


def run_net(root: str, seqs, meta, out: Path):
    t0 = time.time()
    mwe = find_mwe(seqs)
    (out / "mwe_en.json").write_text(json.dumps(mwe, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"mwe merged: {len(mwe)} ({time.time() - t0:.0f}s)", flush=True)

    # ---- 노드 빈도 (글 종류별, 행 기준)
    freq = {r: Counter() for r in ("off", "capt", "capd")}
    nrow = Counter()
    ctx_unit = {r: Counter() for r in ("off", "cap")}   # (event, unit)
    ctx_tot = {r: Counter() for r in ("off", "cap")}
    ctx2_unit, ctx2_tot = Counter(), Counter()           # 캡션: (event×traj, unit)
    lead = {r: defaultdict(Counter) for r in ("off", "capt", "capd")}
    lead_rows = []  # 캡션 설명의 머리 동사·목적어 명사 ↔ 타구 수치
    slot_ctx, slot_tot = Counter(), Counter()  # 자리별(V 머리 동사, O 목적어·제목 머리 명사) 맥락 분포
    for reg, et, tr, w, us, rid in seqs:
        nrow[reg] += w
        keys = {u[0] + "|" + u[1] for u in us}
        for k in keys:
            freq[reg][k] += w
        r2 = "off" if reg == "off" else "cap"
        if et:
            ctx_tot[r2][et] += w
            for k in keys:
                ctx_unit[r2][(et, k)] += w
            lu = lead_unit(reg, us)
            if lu:
                lead[reg][et][lu] += w
            if r2 == "cap":
                c2 = et + (":" + tr if tr and et in ("single", "double", "triple", "field_out", "home_run", "sac_fly") else "")
                ctx2_tot[c2] += w
                for k in keys:
                    ctx2_unit[(c2, k)] += w
                ob = object_noun(us) if reg == "capd" else (lu if (lu and lu.endswith("|N")) else None)
                for slot, key in (("V", lu if (lu and lu.endswith("|V")) else None), ("O", ob)):
                    if key:
                        slot_ctx[(slot + ":" + key, c2)] += w
                        slot_tot[slot + ":" + key] += w
                if reg == "capd" and lu and rid >= 0:
                    lead_rows.append((rid, et, lu, ob or ""))

    # ---- 사건–표현 이분 네트워크
    rows = []
    for r2 in ("off", "cap"):
        n_all = sum(ctx_tot[r2].values())
        ufreq = Counter()
        for (et, k), c in ctx_unit[r2].items():
            ufreq[k] += c
        for (et, k), c in ctx_unit[r2].items():
            if c < 10 or ufreq[k] < NODE_MIN:
                continue
            p_u_e, p_e_u = c / ctx_tot[r2][et], c / ufreq[k]
            pmi = math.log2((c / n_all) / ((ctx_tot[r2][et] / n_all) * (ufreq[k] / n_all)))
            rows.append((r2, et, k, c, round(p_u_e, 4), round(p_e_u, 4), round(pmi, 3)))
    bip = pd.DataFrame(rows, columns=["register", "event_type", "unit", "count", "p_unit_given_event", "p_event_given_unit", "pmi"])
    bip.to_csv(out / "bip_en.csv", index=False)

    # ---- 기의 하나당 기표 수: 사건별 머리 표현의 분포
    rows = []
    for reg in ("off", "capt", "capd"):
        for et, cnt in lead[reg].items():
            tot = sum(cnt.values())
            if tot < 200:
                continue
            ps = np.array([c / tot for c in cnt.values()])
            h = float(-(ps * np.log(ps)).sum())
            top = cnt.most_common(12)
            rows.append((reg, et, tot, sum(1 for c in cnt.values() if c >= 5), round(math.exp(h), 2), round(top[0][1] / tot, 3),
                         "; ".join(f"{k.split('|')[0]} {c / tot:.1%}" for k, c in top)))
    lead_df = pd.DataFrame(rows, columns=["register", "event_type", "rows", "n_lead_ge5", "effective_n", "top1_share", "top12"])
    lead_df.sort_values(["event_type", "register"]).to_csv(out / "lead_en.csv", index=False)

    # ---- 동사별 타구 수치
    lr = pd.DataFrame(lead_rows, columns=["rid", "event_type", "lead", "obj"]).merge(
        meta[["launch_speed", "launch_angle", "distance", "rbi", "wpa_bat", "li"]], left_on="rid", right_index=True)
    g = lr.groupby(["event_type", "lead"]).agg(
        n=("rid", "size"), speed=("launch_speed", "mean"), speed_sd=("launch_speed", "std"), angle=("launch_angle", "mean"),
        angle_sd=("launch_angle", "std"), dist=("distance", "mean"), dist_sd=("distance", "std"), n_dist=("distance", "count"),
        rbi=("rbi", "mean"), wpa=("wpa_bat", "mean"), li=("li", "mean")).reset_index()
    g[g.n >= 60].round(2).sort_values(["event_type", "n"], ascending=[True, False]).to_csv(out / "nuance_en.csv", index=False)
    g2 = lr[lr.obj != ""].groupby(["event_type", "obj"]).agg(
        n=("rid", "size"), speed=("launch_speed", "mean"), angle=("launch_angle", "mean"), dist=("distance", "mean"),
        dist_sd=("distance", "std"), n_dist=("distance", "count"), rbi=("rbi", "mean"), wpa=("wpa_bat", "mean")).reset_index()
    g2[g2.n >= 60].round(2).sort_values(["event_type", "n"], ascending=[True, False]).to_csv(out / "nuance_obj_en.csv", index=False)
    lr.to_csv(out / "lead_rows_en.csv.gz", index=False)

    # ---- 공출현 네트워크: 기록 문장 / 캡션 / 전체
    summary = {"rows": dict(nrow), "holdout_from": X.HOLDOUT_FROM, "mwe": len(mwe)}
    node_tab = {}
    for name, regs in (("off", {"off"}), ("cap", {"capt", "capd"}), ("all", {"off", "capt", "capd"})):
        t1 = time.time()
        f, nodes, edges, n_sent = cooc_network(seqs, regs)
        pd.DataFrame(edges, columns=["a", "b", "count", "npmi"]).to_csv(out / f"cooc_{name}_en.csv", index=False)
        giant, part, deg, strength, core, btw, st = graph_stats(nodes, edges)
        st.update({"sentences": n_sent, "vocab_all": len(f), "vocab_ge_min": len(nodes)})
        summary["cooc_" + name] = st
        node_tab[name] = (f, part, deg, strength, core, btw)
        if name == "cap":
            import networkx as nx
            for n in giant:
                giant.nodes[n].update({"label": n.split("|")[0], "cls": n.split("|")[1], "community": int(part[n]),
                                       "freq": int(f[n]), "kcore": int(core[n])})
            nx.write_gexf(giant, out / "net_cap_en.gexf")
        print(f"cooc {name}: {st} ({time.time() - t1:.0f}s)", flush=True)

    # ---- 노드 표
    allk = set()
    for r in freq:
        allk |= {k for k, c in freq[r].items() if c >= 5}
    ev_tot = defaultdict(Counter)
    for (et, k), c in ctx_unit["cap"].items():
        ev_tot[k][et] += c
    ev_off = defaultdict(Counter)
    for (et, k), c in ctx_unit["off"].items():
        ev_off[k][et] += c
    rows = []
    for k in allk:
        u, c = k.rsplit("|", 1)
        rec = {"unit": u, "cls": c, "f_off": freq["off"][k], "f_capt": freq["capt"][k], "f_capd": freq["capd"][k]}
        for nm, ev in (("cap", ev_tot[k]), ("off", ev_off[k])):
            tot = sum(ev.values())
            if tot:
                top, tc = ev.most_common(1)[0]
                ps = np.array([v / tot for v in ev.values()])
                rec.update({f"top_event_{nm}": top, f"spec_{nm}": round(tc / tot, 3), f"event_entropy_{nm}": round(float(-(ps * np.log2(ps)).sum()), 3)})
        for nm in ("off", "cap", "all"):
            f, part, deg, strength, core, btw = node_tab[nm]
            if k in part:
                rec.update({f"comm_{nm}": part[k], f"deg_{nm}": deg[k], f"str_{nm}": round(strength[k], 3),
                            f"core_{nm}": core[k], f"btw_{nm}": round(btw[k], 6)})
        rows.append(rec)
    nodes_df = pd.DataFrame(rows).sort_values("f_capd", ascending=False)
    nodes_df.to_csv(out / "nodes_en.csv", index=False)

    # ---- 계열 관계: 같은 자리(머리 동사 / 목적어 명사)에서 같은 사건 맥락(사건×타구 모양)을 가리키는 표현끼리.
    ctxs = [c for c, t in ctx2_tot.items() if t >= 300]
    cidx = {c: i for i, c in enumerate(ctxs)}
    keep = [k for k, c in slot_tot.items() if c >= 40]
    kidx = {k: i for i, k in enumerate(keep)}
    M = np.zeros((len(keep), len(ctxs)))
    for (k, c2), c in slot_ctx.items():
        if c2 in cidx and k in kidx:
            M[kidx[k], cidx[c2]] = c
    rs = M.sum(1)
    ok = rs >= 40
    tot = M.sum()
    pm = np.log2((M / tot + 1e-12) / ((M.sum(1, keepdims=True) / tot) * (M.sum(0, keepdims=True) / tot) + 1e-12))
    pm[(pm < 0) | (M < 5)] = 0
    norm = np.linalg.norm(pm, axis=1, keepdims=True) + 1e-12
    S = (pm / norm) @ (pm / norm).T
    P = M / np.maximum(M.sum(1, keepdims=True), 1)
    rows, slot_rows = [], []
    for i, k in enumerate(keep):
        if not ok[i]:
            continue
        j0 = int(P[i].argmax())
        slot_rows.append((k[0], k[2:], int(rs[i]), ctxs[j0], round(float(P[i, j0]), 3)))
        got = 0
        for j in np.argsort(-S[i]):
            if j == i or S[i, j] < 0.5 or not ok[j] or keep[j][0] != k[0]:
                continue
            rows.append((k[0], k[2:], keep[j][2:], round(float(S[i, j]), 3), int(rs[i]), int(rs[j])))
            got += 1
            if got >= 15:
                break
    pd.DataFrame(rows, columns=["slot", "a", "b", "cos", "f_a", "f_b"]).to_csv(out / "para_en.csv", index=False)
    pd.DataFrame(slot_rows, columns=["slot", "unit", "n", "top_context", "share"]).sort_values(["slot", "n"], ascending=[True, False]).to_csv(out / "slots_en.csv", index=False)
    summary["para"] = {"contexts": len(ctxs), "slot_units": int(ok.sum()), "edges": len(rows)}

    # ---- 질문 1: 말의 묶음(공출현 커뮤니티)은 기록원의 분류(사건 종류)와 같은가
    from sklearn.metrics import adjusted_mutual_info_score, normalized_mutual_info_score
    q = nodes_df[nodes_df.comm_cap.notna() & (nodes_df.spec_cap >= 0.5) & ((nodes_df.f_capt + nodes_df.f_capd) >= 50)].copy()
    q["arena"] = q.top_event_cap.map(ARENA).fillna("run")
    big = q.comm_cap.value_counts()
    q = q[q.comm_cap.isin(big[big >= 20].index)]
    summary["q1"] = {
        "nodes": int(len(q)),
        "nmi_event": round(float(normalized_mutual_info_score(q.top_event_cap, q.comm_cap)), 3),
        "ami_event": round(float(adjusted_mutual_info_score(q.top_event_cap, q.comm_cap)), 3),
        "nmi_arena": round(float(normalized_mutual_info_score(q.arena, q.comm_cap)), 3),
        "ami_arena": round(float(adjusted_mutual_info_score(q.arena, q.comm_cap)), 3),
        "table_event": pd.crosstab(q.comm_cap.astype(int), q.top_event_cap).to_dict(),
        "table_arena": pd.crosstab(q.comm_cap.astype(int), q.arena).to_dict(),
    }
    summary["contexts"] = {c: int(ctx2_tot[c]) for c in ctxs}
    (out / "net_en.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done ({time.time() - t0:.0f}s)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--step", default="seqs", choices=["seqs", "net"])
    a = ap.parse_args()
    out = X.lex_dir(a.root)
    cache = out / "seqs_en.pkl"
    if a.step == "seqs":
        t0 = time.time()
        seqs, meta = build_seqs(a.root)
        with open(cache, "wb") as f:
            pickle.dump((seqs, meta), f, protocol=4)
        print(f"seqs {len(seqs)} rows, meta {len(meta)} ({time.time() - t0:.0f}s)")
    else:
        with open(cache, "rb") as f:
            seqs, meta = pickle.load(f)
        run_net(a.root, seqs, meta, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
