"""dissect 결과를 Markdown 보고서로. 팀원(비전공자)이 읽는 문서이므로 라벨은 한국어, 원문은 영어 그대로."""

from __future__ import annotations

from .dissect import Dissection, Play, selection_summary

HALF = {"top": "초", "bottom": "말"}
KIND = {"quote": "인용", "play": "플레이", "aggregate": "집계", "context": "맥락"}


def _cell(text: object) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _num(x: float | None, digits: int = 1, signed: bool = False) -> str:
    if x is None:
        return ""
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def _score(p: Play, d: Dissection) -> str:
    return f"{p.away_after}-{p.home_after}"


def _table(header: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render(d: Dissection) -> str:
    out: list[str] = []
    title = f"{d.away_abbr}@{d.home_abbr} {d.official_date}"
    out.append(f"# 한 경기 분석: {title} (gamePk {d.game_pk})\n")
    out.append(
        "같은 경기 하나에 붙은 세 겹의 텍스트 — 공식 기록 문장(register 1), 하이라이트 캡션(register 2), "
        "리캡 기사(register 3) — 를 타석 단위로 나란히 놓았다. 캡션은 playId 로 정확히 붙고, 기사는 이름·사건 키워드 "
        "휴리스틱으로 붙였다(§7). `mlbcorpus dissect --pk {pk}` 로 재생성.\n".format(pk=d.game_pk)
    )

    # 1. 개요 ----------------------------------------------------------------
    out.append("## 1. 경기 개요\n")
    rec = d.recap_en
    rows: list[list[object]] = [
        ["경기", f"{d.away_name} @ {d.home_name}, {d.official_date}, {d.venue}"],
        ["최종 점수", f"{d.away_abbr} {d.away_score} - {d.home_score} {d.home_abbr}"],
        ["관중 / 경기 시간", f"{d.attendance:,} / {d.duration_minutes}분" if d.attendance else ""],
        ["타석 / 투구", f"{len(d.plays)} / {d.n_pitches}"],
        ["하이라이트 (플레이에 붙는 것)", f"{d.n_highlights} ({d.n_highlights_with_play_id})"],
        ["승리확률 항목", str(d.n_winprob)],
    ]
    if rec:
        rows += [
            ["리캡 제목 (EN)", rec.headline],
            ["기자", ", ".join(rec.authors)],
            ["리캡 길이", f"{rec.body_chars:,}자(HTML) / 단락 {len(rec.paragraphs)} / 문장 {len(rec.sentences)} / 인용문 {rec.n_quotes}"],
        ]
    if d.recap_es:
        rows.append(["리캡 제목 (ES)", d.recap_es.headline])
    out.append(_table(["항목", "값"], rows) + "\n")

    # 2. 세 register -----------------------------------------------------------
    out.append("## 2. 같은 플레이, 세 가지 말투\n")
    out.append("캡션과 기사 문장이 둘 다 붙은 타석부터, 없으면 캡션이 붙은 타석 순으로 최대 5개.\n")
    showcase = sorted(
        (p for p in d.plays if p.captions),
        key=lambda p: (-(1 if p.mentioned else 0), -abs(p.home_wpa or 0)),
    )[:5]
    for p in showcase:
        out.append(f"**#{p.at_bat_index} {p.inning}회{HALF[p.half]} {p.batter.full_name} vs {p.pitcher.full_name} — {p.event}**  ")
        out.append(f"- 기록 문장: {p.description}")
        for c in p.captions:
            pitch = "" if c.is_last_pitch else f" (투구 {c.pitch_number})"
            out.append(f"- 캡션{pitch}: {c.description or c.title}")
        if rec and p.sentence_ids:
            for sid in p.sentence_ids:
                s = rec.sentences[sid - 1]
                out.append(f"- 기사 S{sid}: {s.text}")
        else:
            out.append("- 기사: 언급 없음")
        stat = f"공격팀 승률 {_num(p.wpa_batting, 1, True)}%p, 레버리지 {_num(p.leverage_index, 2)}, 흥미도 {p.captivating_index}"
        if p.launch_speed:
            stat += f", 타구 {p.launch_speed} mph / {p.hit_distance} ft"
        out.append(f"- 수치: {stat}\n")

    # 3. 타석별 정렬표 ---------------------------------------------------------
    out.append("## 3. 타석별 정렬표\n")
    out.append(
        "기사 열은 그 타석을 가리키는 리캡 문장 번호(§5). 승률 변화는 공격팀 관점 %p, 레버리지는 타석 시작 시점, "
        "흥미도는 MLB 가 붙이는 captivatingIndex.\n"
    )
    rows = []
    for p in d.plays:
        caption = " / ".join(c.description or c.title for c in p.captions)
        rows.append([
            p.at_bat_index,
            f"{p.inning}{HALF[p.half]}",
            f"{p.batter.full_name} vs {p.pitcher.last_name}",
            p.event,
            _score(p, d),
            p.description,
            caption,
            ", ".join(f"S{s}" for s in p.sentence_ids),
            _num(p.wpa_batting, 1, True),
            _num(p.leverage_index, 2),
            p.captivating_index,
        ])
    out.append(_table(["#", "이닝", "타자 vs 투수", "결과", "점수", "기록 문장", "캡션", "기사", "승률Δ", "LI", "흥미도"], rows) + "\n")

    # 4. 기자는 무엇을 골랐나 -------------------------------------------------
    out.append("## 4. 기자는 무엇을 골랐나\n")
    sm = selection_summary(d)
    m, u = sm["mentioned"], sm["unmentioned"]
    out.append(_table(
        ["", "타석 수", "평균 \\|승률Δ\\|", "평균 흥미도", "홈런", "안타", "득점", "캡션 있음"],
        [
            ["기사에 언급됨", m["n"], m["mean_abs_wpa"], m["mean_captivating"], m["home_runs"], m["hits"], m["runs"], m["with_caption"]],
            ["언급 안 됨", u["n"], u["mean_abs_wpa"], u["mean_captivating"], u["home_runs"], u["hits"], u["runs"], u["with_caption"]],
        ],
    ) + "\n")
    out.append(
        f"득점이 난 타석 {sm['scoring']}개 중 기사에 언급된 것 {sm['scoring_and_mentioned']}개. "
        f"캡션이 붙은 타석 {sm['captioned']}개 중 기사에도 언급된 것 {sm['captioned_and_mentioned']}개.\n"
    )
    out.append("승률을 가장 많이 움직인 타석 10개:\n")
    rows = []
    for p in sm["top_wpa"]:
        rows.append([
            p.at_bat_index, f"{p.inning}{HALF[p.half]}", p.batter.full_name, p.event, _score(p, d),
            _num(p.wpa_batting, 1, True), _num(p.leverage_index, 2), p.captivating_index,
            "○" if p.captions else "", "○" if p.mentioned else "",
        ])
    out.append(_table(["#", "이닝", "타자", "결과", "점수", "승률Δ", "LI", "흥미도", "캡션", "기사"], rows) + "\n")

    # 5. 리캡 문장표 -----------------------------------------------------------
    if rec:
        out.append("## 5. 리캡 문장표 (EN)\n")
        out.append(
            f"데이트라인 **{rec.dateline}**. 종류: 인용 = 따옴표 안, 플레이 = 특정 타석을 가리킴, 집계 = 여러 타석·박스스코어를 합쳐야 확인됨, "
            "맥락 = 경기 기록으로 확인할 수 없음. 판정은 기록과 대조한 결과.\n"
        )
        rows = []
        for s in rec.sentences:
            rows.append([
                f"S{s.sid}", s.paragraph, KIND[s.kind], s.text,
                ", ".join(p.last_name for p in s.mentions),
                ", ".join(f"#{i}" for i in s.plays), s.verdict, s.evidence,
            ])
        out.append(_table(["문장", "단락", "종류", "원문", "언급 선수", "대응 타석", "판정", "근거"], rows) + "\n")
        counts = {k: sum(1 for s in rec.sentences if s.kind == k) for k in KIND}
        out.append(
            f"문장 {len(rec.sentences)}개 = 인용 {counts['quote']} + 플레이 {counts['play']} + 집계 {counts['aggregate']} + 맥락 {counts['context']}. "
            f"기록으로 확인되는 문장(플레이+집계) {counts['play'] + counts['aggregate']}개, "
            f"그중 판정 '확인' {sum(1 for s in rec.sentences if s.verdict == '확인')}개, '불일치' {sum(1 for s in rec.sentences if s.verdict == '불일치')}개.\n"
        )

    # 6. EN / ES ---------------------------------------------------------------
    if rec and d.recap_es:
        es = d.recap_es
        out.append("## 6. 영어판과 스페인어판\n")
        out.append(_table(
            ["", "EN", "ES"],
            [
                ["제목", rec.headline, es.headline],
                ["기자", ", ".join(rec.authors), ", ".join(es.authors)],
                ["길이(HTML 자)", f"{rec.body_chars:,}", f"{es.body_chars:,}"],
                ["단락 / 문장 / 인용문", f"{len(rec.paragraphs)} / {len(rec.sentences)} / {rec.n_quotes}", f"{len(es.paragraphs)} / {len(es.sentences)} / {es.n_quotes}"],
                ["첫 단락", rec.paragraphs[0] if rec.paragraphs else "", es.paragraphs[0] if es.paragraphs else ""],
                ["마지막 단락", rec.paragraphs[-1] if rec.paragraphs else "", es.paragraphs[-1] if es.paragraphs else ""],
            ],
        ) + "\n")
        out.append("스페인어판 단락 전체:\n")
        for i, para in enumerate(es.paragraphs, start=1):
            out.append(f"{i}. {para}")
        out.append("")

    # 7. 방법과 한계 -----------------------------------------------------------
    out.append("## 7. 방법과 한계\n")
    out.append(
        "- 캡션 ↔ 타석: 하이라이트의 `guid` 가 투구의 `playId` 와 같다. 마지막 투구가 아닌 투구(예: ABS 챌린지 영상)에 붙으면 투구 번호를 표시했다.\n"
        "- 기사 ↔ 타석: 문장에서 경기 로스터(56명)의 이름을 찾고, 사건 키워드(homer/double/walk/struck out …), 이닝 서수(in the fourth), "
        "타점 수식어(solo/two-run)로 후보 타석을 좁혔다. `surrendered/allowed/gave up` 뒤의 사건은 투수 쪽으로 붙인다. "
        "`four-hit`, `three-RBI`, `N-for-M`, `N perfect innings`, `N scoreless frames`, `allowed a run in the ninth`, `knocked in runs`, "
        "`a triple shy of the cycle` 는 여러 타석이나 박스스코어를 합쳐 대조했다.\n"
        "- 로스터 밖 인물(감독·단장·부상자·이적 선수)은 찾지 않는다. 성이 같은 선수(이 경기: Hernández, Stewart)는 출전 선수를 우선하고, 그래도 겹치면 '모호'로 남긴다.\n"
        "- 따옴표 안 문장은 내용과 무관하게 '인용'으로 두었다. 인용 안의 사실 주장은 이번 판에서 대조하지 않는다.\n"
        "- 이 규칙들은 docs/02-schema.md §4 파생 테이블(article_sentences · entity_mentions · sentence_play_alignment)의 초안이다. "
        "여러 경기에 돌려 보면 빠지는 표현이 나올 것이고, 그 목록이 곧 다음 작업이다.\n"
    )
    return "\n".join(out)
