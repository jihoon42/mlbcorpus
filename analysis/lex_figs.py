#!/usr/bin/env python3
"""표현 네트워크 결과 그림 (docs/figs/lexnet/). 입력은 lex_network.py 의 출력.

  fig1_signifiers.png   한 사건을 가리키는 표현은 몇 가지인가 (글 종류별)
  fig2_bipartite.png    사건–머리 동사 이분 네트워크 (기록 문장 대 캡션)
  fig3_communities.png  캡션 공출현 네트워크와 네 묶음
  fig4_nuance.png       같은 홈런·안타라도 동사에 따라 타구가 다른가

사용:  python3 analysis/lex_figs.py            (한글 글꼴: NanumGothic, 없으면 AppleGothic 등)
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
LEX = ROOT / "data" / "tables" / "lex"
OUT = ROOT / "docs" / "figs" / "lexnet"

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"  # 범주색 1~3번 (세 개까지는 산점도에서도 구분 검사를 통과한다)
DIM = "#d9d8d2"

EVENT_KO = {
    "home_run": "홈런", "single": "단타", "double": "2루타", "triple": "3루타", "strikeout": "삼진", "walk": "볼넷",
    "field_out": "범타 (땅볼·뜬공 아웃)", "sac_fly": "희생플라이", "grounded_into_double_play": "병살타",
    "force_out": "포스아웃", "field_error": "실책 출루", "hit_by_pitch": "몸에 맞는 공",
}
STATE_VERBS = {"give", "put", "lead", "open", "tie", "cut", "extend", "get", "take", "score", "plate", "drive in",
               "throw out", "make", "bring home", "bring in", "increase", "trim", "double", "push", "add", "pad",
               "start", "pull", "break", "even", "cap", "follow", "come through", "deliver", "notch", "collect", "record",
               "reach", "leg out", "beat out", "load", "keep", "move", "set", "pick up", "go", "come", "have", "knot"}


def setup_font():
    for fp in list(Path(os.path.expanduser("~/fonts")).glob("NanumGothic*.ttf")):
        font_manager.fontManager.addfont(str(fp))
    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("NanumGothic", "AppleGothic", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR"):
        if cand in names:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams.update({
        "axes.unicode_minus": False, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2, "text.color": INK,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False, "font.size": 11,
        "axes.titlesize": 15, "axes.titleweight": "bold", "axes.titlelocation": "left",
    })


def titled(fig, title, sub, y=0.985, dy=0.045):
    fig.text(0.02, y, title, fontsize=16, fontweight="bold", color=INK, va="top")
    fig.text(0.02, y - dy, sub, fontsize=10.5, color=INK2, va="top")


def parse_top(s: str):
    out = []
    for part in s.split("; "):
        name, share = part.rsplit(" ", 1)
        out.append((name, float(share.rstrip("%")) / 100))
    return out


# ------------------------------------------------------------------ fig 1
def fig1(lead):
    evs = [e for e in EVENT_KO if e in set(lead.event_type)]
    piv = lead[lead.event_type.isin(evs)].pivot(index="event_type", columns="register", values="effective_n")
    piv = piv.loc[sorted(evs, key=lambda e: piv.loc[e, "capd"])]
    fig, ax = plt.subplots(figsize=(9.2, 6.2))
    fig.subplots_adjust(left=0.24, right=0.96, top=0.80, bottom=0.11)
    ys = np.arange(len(piv))
    for y, e in zip(ys, piv.index):
        vals = [piv.loc[e, r] for r in ("off", "capt", "capd")]
        ax.plot([min(vals), max(vals)], [y, y], color=AXIS, lw=1, zorder=1)
    for reg, col, lab in (("off", C1, "기록 문장"), ("capt", C2, "캡션 제목"), ("capd", C3, "캡션 설명")):
        ax.plot(piv[reg], ys, "o", ms=10, color=col, mec=SURFACE, mew=2, label=lab, zorder=3)
    top = piv.index[-1]
    for reg, dx in (("off", 0), ("capt", 0), ("capd", 0)):
        ax.annotate(f"{piv.loc[top, reg]:.1f}", (piv.loc[top, reg], ys[-1]), xytext=(0, 11), textcoords="offset points",
                    ha="center", fontsize=9.5, color=INK2)
    ax.set_xscale("log")
    ax.set_xlim(0.9, 60)
    ax.set_xticks([1, 2, 5, 10, 20, 50])
    ax.set_xticklabels(["1", "2", "5", "10", "20", "50"])
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_yticks(ys)
    ax.set_yticklabels([EVENT_KO[e] for e in piv.index], fontsize=11)
    ax.set_ylim(-0.6, len(piv) - 0.3)
    ax.grid(axis="x", color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("머리 표현의 유효 가짓수 (로그 눈금)")
    ax.legend(loc="lower right", frameon=False, fontsize=10.5, handletextpad=0.3)
    titled(fig, "한 사건을 가리키는 표현은 몇 가지인가",
           "문장의 머리 표현(첫 동사, 제목은 머리 명사)이 사건별로 몇 가지나 쓰이는지. 유효 가짓수 = exp(엔트로피).\n"
           "2019년~2026년 8월, 기록 문장 135만 타석과 타석에 붙은 캡션 18만 건.", dy=0.05)
    fig.savefig(OUT / "fig1_signifiers.png", dpi=170)
    plt.close(fig)
    return piv


# ------------------------------------------------------------------ fig 2
def fig2(lead):
    evs = ["home_run", "single", "double", "strikeout", "field_out"]
    off = {e: [(n, s) for n, s in parse_top(lead[(lead.event_type == e) & (lead.register == "off")].top12.iloc[0]) if s >= 0.03] for e in evs}
    cap = {e: [(n, s) for n, s in parse_top(lead[(lead.event_type == e) & (lead.register == "capd")].top12.iloc[0])][:8] for e in evs}
    best = {}
    for e in evs:
        for n, s in cap[e]:
            if n not in best or s > best[n][1]:
                best[n] = (e, s)
    right = sorted(best, key=lambda n: (evs.index(best[n][0]), -best[n][1]))
    left = []
    for e in evs:
        for n, s in off[e]:
            if n not in left:
                left.append(n)
    H = max(len(right), 12)
    yr = {n: H - 1 - i * (H - 1) / (len(right) - 1) for i, n in enumerate(right)}
    ye = {e: H - 1 - (i + 0.5) * H / len(evs) + 0.5 for i, e in enumerate(evs)}
    yl = {}
    for e in evs:  # 왼쪽은 사건 높이 둘레에 모은다
        ns = [n for n, s in off[e] if n not in yl]
        for k, n in enumerate(ns):
            yl[n] = ye[e] + (len(ns) - 1) / 2 * 1.5 - k * 1.5
    fig, ax = plt.subplots(figsize=(10.2, 8.4))
    fig.subplots_adjust(left=0.03, right=0.97, top=0.86, bottom=0.04)
    xl, xe, xr = 0.0, 1.0, 2.0
    for e in evs:
        for n, s in off[e]:
            ax.plot([xl + 0.02, xe - 0.02], [yl[n], ye[e]], color=C1, lw=max(0.6, 9 * s), alpha=0.75, solid_capstyle="round", zorder=1)
        for n, s in cap[e]:
            ax.plot([xe + 0.02, xr - 0.02], [ye[e], yr[n]], color=C2, lw=max(0.6, 9 * s), alpha=0.6, solid_capstyle="round", zorder=1)
    for n, y in yl.items():
        ax.plot(xl, y, "o", ms=9, color=C1, mec=SURFACE, mew=2, zorder=3)
        sh = max(s for e in evs for m, s in off[e] if m == n)
        ax.text(xl - 0.05, y, f"{n}  {sh:.0%}", ha="right", va="center", fontsize=11.5, color=INK)
    for e, y in ye.items():
        ax.text(xe, y, EVENT_KO[e].split(" (")[0], ha="center", va="center", fontsize=13, fontweight="bold", color=INK,
                bbox=dict(boxstyle="round,pad=0.45", fc=SURFACE, ec=AXIS, lw=1), zorder=4)
    for n, y in yr.items():
        ax.plot(xr, y, "o", ms=9, color=C2, mec=SURFACE, mew=2, zorder=3)
        e, s = best[n]
        ax.text(xr + 0.05, y, f"{n}  {s:.0%}", ha="left", va="center", fontsize=11.5, color=INK)
    ax.text(xl, H + 0.4, "기록 문장의 머리 동사", ha="center", fontsize=11.5, color=INK2, fontweight="bold")
    ax.text(xe, H + 0.4, "사건", ha="center", fontsize=11.5, color=INK2, fontweight="bold")
    ax.text(xr, H + 0.4, "캡션 설명의 머리 동사 (사건별 상위 8개)", ha="center", fontsize=11.5, color=INK2, fontweight="bold")
    ax.set_xlim(-0.75, 2.75)
    ax.set_ylim(-1.0, H + 1.0)
    ax.axis("off")
    titled(fig, "같은 사건, 다른 말: 기록 문장은 한두 가지, 캡션은 수십 가지",
           "선 굵기와 숫자는 그 사건의 문장 가운데 그 동사로 시작하는 비율 (동사가 여러 사건에 걸치면 가장 큰 비율). "
           "캡션 쪽은 상위 8개만 그렸다.", dy=0.04)
    fig.savefig(OUT / "fig2_bipartite.png", dpi=170)
    plt.close(fig)


def place_labels(fig, ax, items, fontsize=10, offsets=((0, 7), (0, -13), (9, -3), (-9, -3), (9, 6), (-9, 6), (0, 15)), halo=True):
    """이름표를 겹치지 않게 놓는다. items = [(글자, (x, y)), ...] 중요한 것부터. 놓을 자리가 없으면 건너뛴다."""
    from matplotlib import patheffects

    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    placed, n_ok = [], 0
    for text, xy in items:
        done = False
        for dx, dy in offsets:
            ha = "center" if dx == 0 else ("left" if dx > 0 else "right")
            t = ax.annotate(text, xy, xytext=(dx, dy), textcoords="offset points", ha=ha, va="center", fontsize=fontsize,
                            color=INK, zorder=7)
            if halo:
                t.set_path_effects([patheffects.withStroke(linewidth=3, foreground=SURFACE)])
            bb = t.get_window_extent(rend).expanded(1.04, 1.12)
            if any(bb.overlaps(o) for o in placed):
                t.remove()
                continue
            placed.append(bb)
            done = True
            n_ok += 1
            break
        if not done:
            continue
    return n_ok


# ------------------------------------------------------------------ fig 3
def fig3(nodes, summary):
    import networkx as nx

    edges = pd.read_csv(LEX / "cooc_cap_en.csv")
    nd = nodes[nodes.comm_cap.notna()].copy()
    nd["key"] = nd.unit + "|" + nd.cls
    nd["f"] = nd.f_capt + nd.f_capd
    arena = pd.DataFrame(summary["q1"]["table_arena"]).fillna(0)
    arena.index = arena.index.astype(int)
    big = nd.comm_cap.value_counts().index[:4].astype(int).tolist()
    names, left_ = {}, list(big)
    for label, col in (("투구·마무리", "pitch"), ("타격·득점", "bat"), ("수비", "field")):
        c = max(left_, key=lambda k: arena.loc[k, col] if k in arena.index else 0)
        names[c] = label
        left_.remove(c)
    names[left_[0]] = "주루·판정"
    by_name = {v: k for k, v in names.items()}
    centers = {by_name["타격·득점"]: (-1.22, 1.12), by_name["수비"]: (1.22, 1.12),
               by_name["투구·마무리"]: (-1.22, -1.12), by_name["주루·판정"]: (1.22, -1.12)}
    comm = dict(zip(nd.key, nd.comm_cap.astype(int)))
    freq = dict(zip(nd.key, nd.f))
    cls = dict(zip(nd.key, nd.cls))
    strength = dict(zip(nd.key, nd.str_cap))
    pos, shown = {}, {}
    for c in big:
        sub = nd[nd.comm_cap == c].sort_values("f", ascending=False).head(70)
        keys = set(sub.key)
        H = nx.Graph()
        H.add_nodes_from(keys)
        for a_, b_, cnt, sc in edges.itertuples(index=False):
            if a_ in keys and b_ in keys and sc >= 0.10:
                H.add_edge(a_, b_, weight=sc)
        p_ = nx.spring_layout(H, weight="weight", k=2.6 / math.sqrt(len(H)), iterations=300, seed=5)
        arr = np.array(list(p_.values()))
        arr = arr - np.median(arr, 0)  # 외딴 점 하나가 묶음 전체를 쪼그라뜨리지 않게 백분위로 맞추고 잘라 낸다
        arr = np.clip(arr / (np.percentile(np.abs(arr), 92, axis=0) + 1e-9) * 0.8, -1.06, 1.06)
        for n, xy in zip(p_.keys(), arr):
            pos[n] = (centers[c][0] + xy[0] * 1.02, centers[c][1] + xy[1] * 0.92)
        shown[c] = H
    fig, ax = plt.subplots(figsize=(13.6, 12.6))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.885, bottom=0.01)
    allkeys = set(pos)
    for a_, b_, cnt, sc in edges.itertuples(index=False):  # 묶음 사이의 강한 연결만 옅게
        if a_ in allkeys and b_ in allkeys and comm[a_] != comm[b_] and sc >= 0.30:
            ax.plot([pos[a_][0], pos[b_][0]], [pos[a_][1], pos[b_][1]], color=GRID, lw=0.4, alpha=0.7, zorder=1)
    for c in big:
        for a_, b_ in shown[c].edges():
            ax.plot([pos[a_][0], pos[b_][0]], [pos[a_][1], pos[b_][1]], color=AXIS, lw=0.45, alpha=0.55, zorder=2)
    col = {"V": C1, "N": C2, "M": C3}
    for k_, lab in (("V", "동사"), ("N", "명사"), ("M", "꾸미는 말")):
        ns = [n for n in pos if cls[n] == k_]
        ax.scatter([pos[n][0] for n in ns], [pos[n][1] for n in ns], s=[26 + 7.0 * math.sqrt(freq[n]) / 3 for n in ns],
                   color=col[k_], edgecolors=SURFACE, linewidths=1.2, zorder=4, label=lab)
    ax.set_xlim(-2.42, 2.42)
    ax.set_ylim(-2.2, 2.32)
    ax.axis("off")
    for c in big:
        n_all = int((nd.comm_cap == c).sum())
        ax.text(centers[c][0], centers[c][1] + 1.06, f"{names[c]}  ·  표현 {n_all}개", ha="center", va="bottom", fontsize=14,
                fontweight="bold", color=INK)
    items = []
    per = {c: sorted([n for n in pos if comm[n] == c], key=lambda n: -strength.get(n, 0)) for c in big}
    for rank in range(70):  # 묶음마다 번갈아 가며 중요한 것부터
        for c in big:
            if rank < len(per[c]):
                items.append((per[c][rank].split("|")[0], pos[per[c][rank]]))
    n_lab = place_labels(fig, ax, items, fontsize=10)
    leg = ax.legend(loc="upper right", ncol=3, frameon=False, fontsize=11, handletextpad=0.2, columnspacing=1.6,
                    bbox_to_anchor=(1.0, 1.035))
    for h in leg.legend_handles:
        h.set_sizes([70])
    st = summary["cooc_cap"]
    q = summary["q1"]
    titled(fig, "캡션의 표현은 사건 종류가 아니라 '누구의 장면인가'로 묶인다",
           f"캡션 공출현 네트워크에서 찾은 커뮤니티 (표현 {st['giant_nodes']}개, 엣지 {st['giant_edges']:,}개, 모듈성 {st['modularity']:.2f}). "
           f"큰 묶음 넷을 떼어 놓고 묶음마다 빈도 상위 70개를 그렸다.\n점은 표현(크기는 빈도), 선은 같은 문장에 우연보다 자주 함께 나온 사이. "
           f"기록원의 사건 분류와의 일치도는 NMI {q['nmi_event']:.2f}, 주인공(타자·야수·투수)으로 나누면 {q['nmi_arena']:.2f}.",
           y=0.988, dy=0.027)
    fig.savefig(OUT / "fig3_communities.png", dpi=150)
    plt.close(fig)
    return names, n_lab


# ------------------------------------------------------------------ fig 4
def fig4(nu):
    skip = STATE_VERBS | {"field", "belt"}
    hr = nu[(nu.event_type == "home_run") & (nu.n_dist >= 200)].copy()
    hr["v"] = hr.lead.str.split("|").str[0]
    hr = hr[hr.lead.str.endswith("|V") & ~hr.v.isin(STATE_VERBS)].sort_values("dist")
    hr["ci"] = 1.96 * hr.dist_sd / np.sqrt(hr.n_dist)
    sg = nu[(nu.event_type == "single") & (nu.n >= 120)].copy()
    sg["v"] = sg.lead.str.split("|").str[0]
    sg = sg[sg.lead.str.endswith("|V") & ~sg.v.isin(skip)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.8, 8.2), gridspec_kw={"width_ratios": [1, 1.2]})
    fig.subplots_adjust(left=0.085, right=0.975, top=0.80, bottom=0.09, wspace=0.24)
    ys = np.arange(len(hr))
    a1.errorbar(hr.dist, ys, xerr=hr.ci, fmt="none", ecolor=AXIS, elinewidth=2, capsize=0, zorder=2)
    a1.plot(hr.dist, ys, "o", ms=9, color=C1, mec=SURFACE, mew=2, zorder=3)
    a1.set_yticks(ys)
    a1.set_yticklabels(hr.v, fontsize=11)
    a1.grid(axis="x", color=GRID, lw=1)
    a1.set_axisbelow(True)
    a1.spines["left"].set_visible(False)
    a1.tick_params(axis="y", length=0)
    a1.set_xlabel("평균 비거리 (피트)")
    a1.set_ylim(-0.7, len(hr) - 0.3)
    for v in ("sky", "line", "lift"):
        r = hr[hr.v == v]
        if len(r):
            a1.annotate(f"발사각 평균 {r.angle.iloc[0]:.0f}°", (r.dist.iloc[0] + r.ci.iloc[0], ys[list(hr.v).index(v)]),
                        xytext=(8, 0), textcoords="offset points", va="center", fontsize=9.5, color=INK2)
    a1.set_title("홈런: 동사에 따라 비거리가 다르다", pad=10)
    a2.plot(sg.speed, sg.angle, "o", ms=9, color=C1, mec=SURFACE, mew=2, zorder=3)
    a2.axhline(0, color=AXIS, lw=1, zorder=1)
    a2.grid(color=GRID, lw=1)
    a2.set_axisbelow(True)
    a2.set_xlabel("평균 타구 속도 (mph)")
    a2.set_ylabel("평균 발사각 (도)")
    a2.set_title("단타: 동사가 타구의 모양을 말해 준다", pad=10)
    sg = sg.assign(far=(np.abs(sg.speed - sg.speed.median()) / sg.speed.std() + np.abs(sg.angle - sg.angle.median()) / sg.angle.std()))
    items = [(r.v, (r.speed, r.angle)) for r in sg.sort_values("far", ascending=False).itertuples()]
    place_labels(fig, a2, items, fontsize=10.5, offsets=((9, 6), (9, -7), (-9, 6), (-9, -7), (0, 12), (0, -13), (14, 0), (-14, 0)))
    titled(fig, "낱말의 뜻은 쓰임: 같은 홈런·안타라도 동사에 따라 실제 타구가 다르다",
           "캡션 설명의 머리 동사별로 그 타석의 Statcast 수치를 평균했다. 왼쪽 막대는 95% 신뢰구간 (동사당 200타석 이상), "
           "오른쪽은 동사당 120타석 이상.\n점수 상황을 말하는 동사(give, tie, extend 등)는 뺐다.", dy=0.042)
    fig.savefig(OUT / "fig4_nuance.png", dpi=160)
    plt.close(fig)
    return hr[["v", "n_dist", "dist", "ci", "speed", "angle"]], sg[["v", "n", "speed", "angle"]]


# ------------------------------------------------------------------ fig 5
def fig5(div):
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 5.6), sharey=False)
    fig.subplots_adjust(left=0.07, right=0.93, top=0.76, bottom=0.11, wspace=0.26)
    for ax, (et, name) in zip(axes, (("home_run", "홈런 캡션"), ("ALL", "모든 사건의 캡션"))):
        for lang, col, lab in (("en", C1, "영어"), ("es", C2, "스페인어")):
            d = div[(div.lang == lang) & (div.event_type == et)].sort_values("season")
            ax.plot(d.season, d.effective_n_at1500, "-o", color=col, lw=2, ms=8, mec=SURFACE, mew=2, label=lab, solid_capstyle="round")
            ax.annotate(f"{d.effective_n_at1500.iloc[0]:.0f}", (d.season.iloc[0], d.effective_n_at1500.iloc[0]), xytext=(-9, 0),
                        textcoords="offset points", ha="right", va="center", fontsize=10.5, color=INK2)
            ax.annotate(f"{lab} {d.effective_n_at1500.iloc[-1]:.0f}", (d.season.iloc[-1], d.effective_n_at1500.iloc[-1]), xytext=(9, 0),
                        textcoords="offset points", ha="left", va="center", fontsize=10.5, color=INK)
        ax.set_ylim(0, None)
        ax.set_xticks(range(2019, 2027))
        ax.set_xlim(2018.4, 2026.6)
        ax.grid(axis="y", color=GRID, lw=1)
        ax.set_axisbelow(True)
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.set_title(name, fontsize=13, pad=8)
    axes[0].set_ylabel("머리 동사의 유효 가짓수")
    axes[0].legend(loc="lower left", frameon=False, fontsize=10.5)
    titled(fig, "홈런 캡션의 동사는 7년 사이 절반으로 줄었다",
           "캡션 설명의 머리 동사가 몇 가지나 쓰이는지 (유효 가짓수). 시즌마다 건수가 달라 1,500건씩 뽑아 맞춘 값이다.\n"
           "모든 사건으로 넓히면 영어만 줄고 스페인어는 그대로다. 2020년은 60경기 단축 시즌, 2026년은 8월까지.", dy=0.055)
    fig.savefig(OUT / "fig5_seasons.png", dpi=170)
    plt.close(fig)


# ------------------------------------------------------------------ fig 6
def fig6(lead_es, spec):
    evs = ["home_run", "single", "double", "strikeout"]
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.9))
    fig.subplots_adjust(left=0.10, right=0.97, top=0.70, bottom=0.14, wspace=0.16)
    ld = lead_es[(lead_es.register == "capd")].pivot(index="event_type", columns="lang", values="effective_n")
    sp = spec[spec.cls == "N"].pivot(index="event_type", columns="lang", values="effective_n")
    for ax, (tab, name, xlab) in zip(axes, ((ld, "문장을 이끄는 동사", "머리 동사의 유효 가짓수"),
                                            (sp, "그 사건에서만 쓰이는 명사", "사건 전용 명사의 유효 가짓수"))):
        ys = np.arange(len(evs))[::-1]
        for y, e in zip(ys, evs):
            ax.plot([tab.loc[e, "en"], tab.loc[e, "es"]], [y, y], color=AXIS, lw=1, zorder=1)
        for lang, col, lab in (("en", C1, "영어"), ("es", C2, "스페인어")):
            ax.plot([tab.loc[e, lang] for e in evs], ys, "o", ms=10, color=col, mec=SURFACE, mew=2, label=lab, zorder=3)
            for y, e in zip(ys, evs):
                other = "es" if lang == "en" else "en"
                right = tab.loc[e, lang] >= tab.loc[e, other]
                ax.annotate(f"{tab.loc[e, lang]:.1f}", (tab.loc[e, lang], y), xytext=(10 if right else -10, 0), textcoords="offset points",
                            ha="left" if right else "right", va="center", fontsize=10, color=INK2)
        ax.set_yticks(ys)
        ax.set_yticklabels([EVENT_KO[e] for e in evs] if ax is axes[0] else [])
        ax.set_ylim(-0.6, len(evs) - 0.4)
        ax.set_xlim(0, float(np.nanmax(tab.loc[evs].values)) * 1.18)
        ax.grid(axis="x", color=GRID, lw=1)
        ax.set_axisbelow(True)
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.set_xlabel(xlab)
        ax.set_title(name, fontsize=13, pad=8)
    axes[0].legend(loc="lower right", frameon=False, fontsize=10.5)
    titled(fig, "영어는 동사를 바꿔 쓰고, 스페인어는 홈런의 이름을 바꿔 쓴다",
           "같은 하이라이트에 붙은 영어 캡션과 스페인어 캡션 15만 쌍. 왼쪽은 문장을 이끄는 동사, 오른쪽은 그 사건에서만 쓰이는 명사\n"
           "(쓰임의 80% 이상이 그 사건인 명사)가 몇 가지나 고르게 쓰이는지.", dy=0.065)
    fig.savefig(OUT / "fig6_en_es.png", dpi=170)
    plt.close(fig)


# ------------------------------------------------------------------ fig 7
def fig7(al):
    v = al[al.slot == "V"].copy()
    en_list = ["crush", "belt", "launch", "hammer", "crank", "smash", "clobber", "hit"]
    v["e"] = v.en.str.split("|").str[0]
    v["s"] = v.es.str.split("|").str[0]
    v = v[v.e.isin(en_list)]
    tot = v.groupby("s")["count"].sum().sort_values(ascending=False)
    es_list = [x for x in tot.index if (v[v.s == x].p_es_given_en >= 0.03).any()][:11]
    v = v[v.s.isin(es_list)]
    H = max(len(en_list), len(es_list))
    ye = {n: H - 1 - i * (H - 1) / (len(en_list) - 1) for i, n in enumerate(en_list)}
    ys_ = {n: H - 1 - i * (H - 1) / (len(es_list) - 1) for i, n in enumerate(es_list)}
    fig, ax = plt.subplots(figsize=(8.6, 7.4))
    fig.subplots_adjust(left=0.03, right=0.97, top=0.82, bottom=0.03)
    for r in v.itertuples():
        if r.p_es_given_en >= 0.02:
            ax.plot([0.03, 0.97], [ye[r.e], ys_[r.s]], color=AXIS, lw=max(0.5, 16 * r.p_es_given_en), alpha=0.55, solid_capstyle="round", zorder=1)
    for n, y in ye.items():
        ax.plot(0, y, "o", ms=10, color=C1, mec=SURFACE, mew=2, zorder=3)
        ax.text(-0.04, y, n, ha="right", va="center", fontsize=12.5, color=INK)
    for n, y in ys_.items():
        ax.plot(1, y, "o", ms=10, color=C2, mec=SURFACE, mew=2, zorder=3)
        ax.text(1.04, y, n, ha="left", va="center", fontsize=12.5, color=INK)
    ax.text(0, H + 0.1, "영어 캡션의 머리 동사", ha="center", fontsize=11.5, color=INK2, fontweight="bold")
    ax.text(1, H + 0.1, "같은 장면의 스페인어 머리 동사", ha="center", fontsize=11.5, color=INK2, fontweight="bold")
    ax.set_xlim(-0.42, 1.5)
    ax.set_ylim(-0.7, H + 0.6)
    ax.axis("off")
    titled(fig, "영어의 홈런 동사는 스페인어에서 어디로 가는가",
           "선 굵기는 그 영어 동사로 시작한 캡션 가운데 스페인어판이 그 동사로 시작한 비율 (2% 이상만).\n"
           "영어의 여러 동사가 conectar 하나로 모이고, despachar·detonar 같은 스페인어 전용 동사는 따로 있다.", dy=0.052)
    fig.savefig(OUT / "fig7_en_es_verbs.png", dpi=170)
    plt.close(fig)


def main() -> int:
    setup_font()
    OUT.mkdir(parents=True, exist_ok=True)
    lead = pd.read_csv(LEX / "lead_en.csv")
    nodes = pd.read_csv(LEX / "nodes_en.csv")
    nu = pd.read_csv(LEX / "nuance_en.csv")
    summary = json.loads((LEX / "net_en.json").read_text(encoding="utf-8"))
    only = set(sys.argv[1:])
    if not only or "1" in only:
        print(fig1(lead).round(2).to_string())
    if not only or "2" in only:
        fig2(lead)
    if not only or "3" in only:
        print(fig3(nodes, summary))
    if not only or "4" in only:
        hr, sg = fig4(nu)
        print(hr.round(1).to_string(index=False))
        print(sg.round(1).sort_values("speed").to_string(index=False))
    if (LEX / "diversity_season.csv").exists():
        if not only or "5" in only:
            fig5(pd.read_csv(LEX / "diversity_season.csv"))
        if not only or "6" in only:
            fig6(pd.read_csv(LEX / "lead_es.csv"), pd.read_csv(LEX / "specific_vocab.csv"))
        if not only or "7" in only:
            fig7(pd.read_csv(LEX / "align_lead.csv"))
    print("font:", plt.rcParams["font.family"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
