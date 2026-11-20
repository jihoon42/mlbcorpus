"""표현 네트워크 스크립트들이 같이 쓰는 읽기·집계 함수."""
from __future__ import annotations

import glob
import gzip
import json
import math
from collections import Counter
from pathlib import Path

import pandas as pd

from lex_units import split_sents

HOLDOUT_FROM = "2026-09-01"  # 이 날짜부터의 경기는 모델을 만들 때 쓰지 않고 점검에만 쓴다


def lex_dir(root=".") -> Path:
    return Path(root) / "data" / "tables" / "lex"


def load_units(root=".", lang="en") -> dict:
    """문장 → [[단위, 종류, 시작, 끝], ...]"""
    out = {}
    for f in sorted(glob.glob(str(lex_dir(root) / f"units_{lang}.s*.jsonl.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                out[d["s"]] = d["u"]
    return out


def load_caps(root=".", cols=None) -> pd.DataFrame:
    fs = sorted(glob.glob(str(lex_dir(root) / "caps.c*.csv.gz")))
    df = pd.concat([pd.read_csv(f, usecols=cols) for f in fs], ignore_index=True)
    return df


def load_plays(root=".", cols=None) -> pd.DataFrame:
    fs = sorted(glob.glob(str(lex_dir(root) / "plays.c*.csv.gz")))
    return pd.concat([pd.read_csv(f, usecols=cols) for f in fs], ignore_index=True)


def text_units(text, units: dict) -> list[list]:
    """글 하나(여러 문장일 수 있음)의 단위 목록. 문장 경계는 자리 번호에 1000 씩 더해 구분한다."""
    out = []
    if not isinstance(text, str) or not text:
        return out
    for si, s in enumerate(split_sents(text)):
        for rec in units.get(s, []):
            u, c, a, b = rec[:4]
            out.append([u, c, si * 1000 + a, si * 1000 + b] + list(rec[4:5]))
    return out


def npmi(c_xy, c_x, c_y, n) -> float:
    if c_xy <= 0:
        return -1.0
    p_xy, p_x, p_y = c_xy / n, c_x / n, c_y / n
    if p_xy >= 1.0:
        return 1.0
    return math.log(p_xy / (p_x * p_y)) / -math.log(p_xy)


def apply_mwe(us: list[list], score: dict) -> list[list]:
    """이미 정해진 묶음 목록(score: (왼쪽, 오른쪽) → 점수)을 새 문장에 적용한다. 점수가 높은 쌍부터."""
    us = [list(u) for u in us]
    while True:
        best, bi_ = None, -1
        for i in range(len(us) - 1):
            a, b = us[i], us[i + 1]
            sc = score.get((a[0], b[0]))
            if sc is not None and a[3] + 1 == b[2] and (best is None or sc > best):
                best, bi_ = sc, i
        if best is None:
            return us
        a, b = us[bi_], us[bi_ + 1]
        new = [a[0] + " " + b[0], "N" if b[1] == "N" else b[1], a[2], b[3]]
        if len(a) > 4 and len(b) > 4:
            new.append(a[4] + " " + b[4])
        us[bi_:bi_ + 2] = [new]


def merge_mwe(seq: list[list], pairs: set) -> list[list]:
    """바로 붙어 있는 두 단위가 pairs 에 있으면 한 단위로 묶는다 (왼쪽부터, 겹치지 않게)."""
    out = []
    i = 0
    while i < len(seq):
        if i + 1 < len(seq) and seq[i][3] + 1 == seq[i + 1][2] and (seq[i][0], seq[i + 1][0]) in pairs:
            out.append([seq[i][0] + " " + seq[i + 1][0], "N" if seq[i + 1][1] == "N" else seq[i + 1][1], seq[i][2], seq[i + 1][3]])
            i += 2
        else:
            out.append(seq[i])
            i += 1
    return out
