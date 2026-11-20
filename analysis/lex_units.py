#!/usr/bin/env python3
"""문장 → 표현 단위 (표현 네트워크의 노드 후보).

입력은 lex_extract.py 가 만든 표(data/tables/lex/)의 '가린 문장'(<P>, <N>)이다.
문장마다 spaCy 로 품사·기본형을 구하고 내용어만 남겨 단위 목록을 만든다.

  V  동사 (기본형. strikes out 같은 구동사는 한 단위)
  N  명사
  M  꾸미는 말 (형용사·부사, two-run / walk-off 같은 하이픈 합성어)

야구 문장에서 품사 태거가 자주 틀리는 자리를 규칙으로 바로잡는다.
  - 주어 바로 뒤 단어는 동사다 ("<P> homers", "<P> clubs" 를 명사로 읽는 오류).
  - 3인칭 단수형의 기본형은 규칙으로 구한다 (plates → plate. 태거는 plat 으로 낸다).

출력: data/tables/lex/units_{lang}.sNN.jsonl.gz  한 줄 = {"s": 문장, "u": [[단위, 종류, 시작, 끝, 글에 나온 꼴], ...]}
      시작·끝은 원래 토큰 자리. 뒤 단계에서 '바로 붙어 있던 단위'를 묶을 때 쓴다.

사용:  python3 analysis/lex_units.py --lang en --nshards 4 --shards 0,1 --procs 4
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
INITIALS = re.compile(r"(?:\b[A-Z]\. ?)+(?=<P>)")
DIGITS = re.compile(r"\d+")
ORD_EN = re.compile(r"\b\d+(?:st|nd|rd|th)\b")
ORD_ES = re.compile(r"\b\d+(?:ra|ro|do|da|to|ta|mo|ma|vo|va|no|na|er)\b")
ORD = re.compile(r"^5(?:th|ta)$")
PH = {"en": ("Smith", "Tigers"), "es": ("Soto", "Tigres")}
TEAMS = ("Angels|Astros|Athletics|Blue Jays|Braves|Brewers|Cardinals|Cubs|D-backs|Diamondbacks|Dodgers|Giants|Guardians|"
         "Indians|Mariners|Marlins|Mets|Nationals|Orioles|Padres|Phillies|Pirates|Rangers|Rays|Red Sox|Reds|Rockies|"
         "Royals|Tigers|Twins|White Sox|Yankees")
TEAM_RX = re.compile(r"(?<![\w<])(?:" + TEAMS + r")(?![\w>])")

KEEP = {"VERB": "V", "NOUN": "N", "ADJ": "M", "ADV": "M", "PROPN": "N"}
ADV_STOP = {"then", "just", "also", "there", "here", "now", "not", "so", "as", "when", "where", "how", "too", "very",
            "once", "again", "still", "even", "more", "most", "only", "ever", "never", "later", "after", "before",
            "luego", "también", "tambien", "ya", "no", "más", "mas", "muy", "así", "asi", "aquí", "ahí", "solo", "sólo"}
PART_STRONG = {"out", "deep", "yard", "home", "away", "back", "ahead"}
PART_WEAK = {"off", "up", "down", "in", "on", "over", "through", "around"}
LEMMA_FIX = {"plat": "plate", "lac": "lace", "rop": "rope", "skie": "sky", "k": "k", "basis": "base",
             "unassiste": "unassisted", "freez": "freeze"}
MOD_LEX = {"solo", "leadoff", "unassisted"}  # 늘 꾸미는 말로 둔다
# 품사 태거가 동사·형용사로 잘못 읽는 야구 명사. 여기 있는 말은 문장 속 자리와 상관없이 명사로 둔다.
NOUN_LEX = {"shortstop", "pitcher", "catcher", "baseman", "fielder", "single", "double", "triple", "homer", "middle",
            "left", "right", "center", "groundout", "flyout", "lineout", "popout", "strikeout", "walk-off", "rbi"}
VERB_OK_AFTER_SUBJ = {"single", "double", "triple", "homer"}  # 주어 바로 뒤에서는 동사 (singles, doubles ...)
IRREG_3SG = {"is": "be", "has": "have", "does": "do", "goes": "go", "k's": "k", "ks": "k"}


# 스페인어: 전치사가 낀 굳은 표현은 태거에 넣기 전에 한 토큰으로 붙인다 (base por bolas → base_por_bolas)
ES_MWE = ["base por bolas", "bases por bolas", "golpeado por lanzamiento", "golpeado por un lanzamiento", "elevado de sacrificio",
          "fly de sacrificio", "toque de sacrificio", "jugada de selección", "error de tiro", "error de fildeo",
          "vuelta entera", "cuatro esquinas", "bases llenas", "doble matanza", "doble play", "cuadro interior",
          "línea de foul", "zona de foul", "terreno de foul", "out forzado", "regla de terreno", "robo de base",
          "intento de robo", "bateador emergente", "corredor emergente", "sin hit ni carrera", "juego perfecto"]
ES_MWE_RX = re.compile(r"(?<!\w)(" + "|".join(re.escape(m) for m in sorted(ES_MWE, key=len, reverse=True)) + r")(?!\w)", re.I)
ES_NOUN_LEX = {"sencillo", "doble", "triple", "jonrón", "cuadrangular", "rodado", "elevado", "línea", "roletazo", "imparable",
               "hit", "ponche", "boleto", "capítulo", "episodio", "entrada", "inning", "batazo", "vuelacercas", "bambinazo",
               "tablazo", "estacazo", "toque", "globo", "fly", "out", "doblete", "tubey", "indiscutible", "incogible",
               "palo", "leñazo", "cañonazo", "bombazo", "jonronazo", "tablazo", "hr", "grand slam", "remolcador"}
ES_CLITIC = {"se", "le", "les", "lo", "la", "los", "las", "me", "te", "nos", "no"}
ES_E_VERBS = {"extiende": "extender", "pone": "poner", "rompe": "romper", "recibe": "recibir", "consigue": "conseguir",
              "sacude": "sacudir", "abre": "abrir", "añade": "añadir", "corre": "correr", "produce": "producir",
              "define": "definir", "decide": "decidir", "sale": "salir", "viene": "venir", "tiene": "tener", "hace": "hacer",
              "pierde": "perder", "vuelve": "volver", "mueve": "mover", "cubre": "cubrir", "responde": "responder",
              "sorprende": "sorprender", "impide": "impedir", "consigue": "conseguir", "sigue": "seguir", "sube": "subir",
              "reduce": "reducir", "resuelve": "resolver", "obtiene": "obtener", "mantiene": "mantener", "detiene": "detener",
              "retiene": "retener", "parte": "partir", "bate": "batir", "da": "dar", "va": "ir", "es": "ser", "cae": "caer",
              "trae": "traer", "atrae": "atraer", "luce": "lucir", "une": "unir", "suma": "sumar", "suena": "sonar",
              "vuela": "volar", "cierra": "cerrar", "empieza": "empezar", "comienza": "comenzar", "despierta": "despertar",
              "muestra": "mostrar", "encuentra": "encontrar", "cuelga": "colgar", "suelta": "soltar", "prueba": "probar",
              "vence": "vencer", "convierte": "convertir", "sirve": "servir", "repite": "repetir", "consiente": "consentir",
              "empuja": "empujar", "ancla": "anclar", "pide": "pedir", "elige": "elegir", "sostiene": "sostener"}


def es_join(text: str) -> str:
    return ES_MWE_RX.sub(lambda m: m.group(1).replace(" ", "_"), text)


def es_lemma_3sg(low: str, spacy_lemma: str) -> str:
    if low in ES_E_VERBS:
        return ES_E_VERBS[low]
    spacy_lemma = spacy_lemma.split(" ")[0]
    # 태거의 기본형은 어간이 원형과 맞을 때만 믿는다 (poncha → "ponchaber" 같은 오류가 있다)
    if spacy_lemma.endswith(("ar", "er", "ir")) and low.startswith(spacy_lemma[:-2]):
        return spacy_lemma
    if low.endswith("a") and len(low) > 3:
        return low + "r"
    return low


def normalize(text: str) -> str:
    """가린 문장을 틀로: 숫자는 #, 이름 머리글자(J. D. <P>)는 지우고, 문장 첫머리 팀 이름도 <N> 으로."""
    s = INITIALS.sub("", text)
    s = TEAM_RX.sub("<N>", s)
    s = s.replace("’", "'").replace("\xa0", " ")
    # 서수는 5th(스페인어 5ta), 그 밖의 숫자는 7 로 통일한다. 태거가 읽을 수 있는 모양이어야 해서 # 을 쓰지 않는다.
    s = ORD_EN.sub("\x01", s)
    s = ORD_ES.sub("\x02", s)
    s = DIGITS.sub("7", s)
    s = s.replace("\x01", "5th").replace("\x02", "5ta")
    return re.sub(r"\s+", " ", s).strip()


def split_sents(text: str) -> list[str]:
    return [x for x in SENT_SPLIT.split(normalize(text)) if x]


def lemma_3sg(w: str) -> str:
    w = w.lower()
    if w in IRREG_3SG:
        return IRREG_3SG[w]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("zes") and not w.endswith("zzes"):
        return w[:-1]  # freezes → freeze, squeezes → squeeze
    if re.search(r"(sses|shes|ches|xes|zzes|oes)$", w):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 2:
        return w[:-1]
    return w


def units_of(doc, lang: str) -> list[list]:
    p_name, n_name = PH[lang]
    toks = list(doc)
    n = len(toks)
    out: list[list] = []
    # 주어(<P>) 바로 뒤의 -s 로 끝나는 단어는 동사 (영어). 문장 첫머리에서는 부사가 끼면 한 칸 뒤.
    forced: set[int] = set()
    if lang == "en":
        for a in range(n - 1):
            if toks[a].text != p_name and not (a == 0 and toks[a].text == n_name):
                continue
            k = a + 1
            if a == 0 and toks[k].pos_ == "ADV" and k + 1 < n and toks[k].lower_.endswith("ly"):
                k += 1
            t = toks[k]
            if not t.is_alpha or t.text in (p_name, n_name) or t.pos_ in ("AUX", "ADP", "CCONJ", "SCONJ", "PRON", "DET"):
                continue
            if t.text == "K" and k + 1 < n and toks[k + 1].text == "'s":
                forced.add(k)
            elif t.lower_.endswith("s") and len(t.text) > 3 and t.text.islower():
                forced.add(k)
            elif a == 0 and t.pos_ == "VERB":
                forced.add(k)
    es_forced, es_refl = -1, False
    if lang == "es" and n >= 2 and toks[0].text == p_name:
        k = 1
        while k < n and toks[k].lower_ in ES_CLITIC:
            es_refl = es_refl or toks[k].lower_ == "se"
            k += 1
        if k < n and toks[k].is_alpha and toks[k].text.islower() and toks[k].pos_ not in ("ADP", "CCONJ", "DET", "SCONJ"):
            es_forced = k
    i = 0
    while i < n:
        t = toks[i]
        low = t.lower_
        if lang == "es" and "_" in t.text:
            out.append([low.replace("_", " "), "N", i, i, low.replace("_", " ")])
            i += 1
            continue
        if lang == "es" and low in ES_NOUN_LEX and i != es_forced:
            out.append([low, "M" if low == "remolcador" else "N", i, i, low])
            i += 1
            continue
        if lang == "es" and i == es_forced:
            lem = es_lemma_3sg(low, t.lemma_.lower())
            out.append([lem + ("se" if es_refl and lem.endswith(("ar", "er", "ir")) else ""), "V", i, i, ("se " if es_refl else "") + low])
            i += 1
            continue
        # 하이픈 합성어 다시 붙이기: two - run, walk - off, inside - the - park
        j = i
        parts = [low]
        while j + 2 < n and toks[j].whitespace_ == "" and toks[j + 1].text == "-" and toks[j + 1].whitespace_ == "":
            parts.append(toks[j + 2].lower_)
            j += 2
        if j > i:
            if all(re.fullmatch(r"[a-záéíóúñü']+", p) for p in parts) and p_name.lower() not in parts and n_name.lower() not in parts:
                nxt = toks[j + 1] if j + 1 < n else None
                cls = "M" if (nxt is not None and nxt.pos_ in ("NOUN", "PROPN", "ADJ") and nxt.text not in (p_name, n_name)) else "N"
                out.append(["-".join(parts), cls, i, j, "-".join(parts)])
            i = j + 1
            continue
        if t.text in (p_name, n_name) or t.is_space or t.is_punct or "#" in t.text or ORD.match(t.text):
            i += 1
            continue
        if i in forced:
            lem = lemma_3sg(low) if low.endswith("s") else LEMMA_FIX.get(t.lemma_.lower(), t.lemma_.lower())
            cls = "V"
            if t.text == "K":
                lem = "k"
                out.append([lem, cls, i, i + 1, "k's"])
                i += 2
                continue
        elif lang == "en" and low in ("out", "outs") and i > 0 and (toks[i - 1].pos_ in ("DET", "ADJ", "NUM") or toks[i - 1].text == p_name or ORD.match(toks[i - 1].text)):
            out.append(["out", "N", i, i, low])  # the third out, two outs, "<P> out at 2nd"
            i += 1
            continue
        elif lang == "en" and low == "fielder" and i + 2 < n and toks[i + 1].text == "'s" and toks[i + 2].lower_ == "choice":
            out.append(["fielder's choice", "N", i, i + 2, "fielder's choice"])
            i += 3
            continue
        elif lang == "en" and (low in NOUN_LEX or (low.endswith("s") and low[:-1] in NOUN_LEX and low not in ("homers",) )) and re.fullmatch(r"[a-z\-]+", low):
            base = low if low in NOUN_LEX else low[:-1]
            nxt = toks[i + 1] if i + 1 < n else None
            # NNS + (관사·이름·불변화사) 꼴이면 동사: "and doubles home <P>", "singles in the 4th" 는 드물어 명사로 둔다
            out.append([base, "N", i, i, low])
            i += 1
            continue
        else:
            cls = KEEP.get(t.pos_)
            if cls is None or not re.fullmatch(r"[A-Za-záéíóúñüÁÉÍÓÚÑÜ']+", t.text) or len(low) < 2 and low != "k":
                i += 1
                continue
            if cls == "M" and low in ADV_STOP:
                i += 1
                continue
            lem = t.lemma_.lower()
            if lang == "es":
                lem = lem.split(" ")[0]
            if lang == "en" and cls == "V" and t.tag_ == "VBZ":
                lem = lemma_3sg(low)
            if lang == "en" and t.tag_ == "NNS" and i > 0 and toks[i - 1].lower_ in ("and", ",", "then", "but") and i + 1 < n:
                nx1 = toks[i + 1]
                if nx1.pos_ == "DET" or nx1.text in (p_name, n_name) or nx1.lower_ in PART_STRONG or nx1.lower_ in PART_WEAK:
                    cls, lem = "V", lemma_3sg(low)  # "... and drives in <P>": 복수 명사가 아니라 동사
            lem = LEMMA_FIX.get(lem, lem)
            if lang == "en" and low in MOD_LEX:
                cls, lem = "M", low
        end = i
        surf = low
        if cls == "V" and lang == "en" and i + 1 < n:
            nx = toks[i + 1]
            nlow = nx.lower_
            nn = toks[i + 2] if i + 2 < n else None
            weak_ok = nx.dep_ == "prt" or nn is None or (nn.pos_ not in ("DET", "PROPN", "NUM", "PRON") and nn.text not in (p_name, n_name))
            if nlow == "in" and nn is not None and nn.text == p_name:
                weak_ok = True  # drives in <P>, brings in <P>: 뒤가 사람이면 구동사
            if nlow in PART_STRONG or (nlow in PART_WEAK and weak_ok):
                lem = lem + " " + nlow
                surf = low + " " + nlow
                end = i + 1
        out.append([lem, cls, i, end, surf])
        i = end + 1
    return out


def collect_sentences(root: Path, lang: str) -> list[str]:
    lex = root / "data" / "tables" / "lex"
    sents: set[str] = set()
    cols = {"en": ["guid", "at_bat_index", "title_en_m", "desc_en_m"], "es": ["guid", "at_bat_index", "title_es_m", "desc_es_m"]}[lang]
    for f in sorted(glob.glob(str(lex / "caps.c*.csv.gz"))):
        df = pd.read_csv(f, usecols=cols)
        df = df[df.guid.notna() & df.at_bat_index.notna()]
        for c in cols[2:]:
            for v in df[c].dropna().unique():
                sents.update(split_sents(v))
    if lang == "en":
        for f in sorted(glob.glob(str(lex / "plays.c*.csv.gz"))):
            for v in pd.read_csv(f, usecols=["desc_en_m"]).desc_en_m.dropna().unique():
                sents.update(split_sents(v))
    else:
        for f in sorted(glob.glob(str(lex / "pbp_es.c*.csv.gz"))):
            for v in pd.read_csv(f, usecols=["desc_es_m"]).desc_es_m.dropna().unique():
                sents.update(split_sents(v))
    return sorted(sents)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--lang", default="en", choices=["en", "es"])
    ap.add_argument("--nshards", type=int, default=4)
    ap.add_argument("--shards", default="0")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    import spacy

    root = Path(a.root)
    out_dir = root / "data" / "tables" / "lex"
    t0 = time.time()
    cache = out_dir / f"sentences_{a.lang}.txt.gz"
    if cache.exists() and not a.force:
        with gzip.open(cache, "rt", encoding="utf-8") as f:
            sents = [x.rstrip("\n") for x in f]
    else:
        sents = collect_sentences(root, a.lang)
        with gzip.open(cache, "wt", encoding="utf-8") as f:
            f.write("\n".join(sents) + "\n")
    print(f"{len(sents)} unique sentences ({time.time() - t0:.1f}s)", flush=True)
    nlp = spacy.load({"en": "en_core_web_sm", "es": "es_core_news_sm"}[a.lang], disable=["ner"])
    p_name, n_name = PH[a.lang]
    for sh in [int(x) for x in a.shards.split(",") if x.strip() != ""]:
        out = out_dir / f"units_{a.lang}.s{sh:02d}.jsonl.gz"
        if out.exists() and not a.force:
            print(f"shard {sh}: skip", flush=True)
            continue
        mine = sents[sh::a.nshards]
        t1 = time.time()
        texts = [s.replace("<P>", p_name).replace("<N>", n_name) for s in mine]
        if a.lang == "es":
            texts = [es_join(x) for x in texts]
        tmp = out.with_name(out.name + ".part")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=5) as f:
            for s, doc in zip(mine, nlp.pipe(texts, batch_size=512, n_process=a.procs)):
                f.write(json.dumps({"s": s, "u": units_of(doc, a.lang)}, ensure_ascii=False) + "\n")
        tmp.replace(out)
        print(f"shard {sh}: {len(mine)} sentences in {time.time() - t1:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
