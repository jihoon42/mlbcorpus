from mlbcorpus.schedule import is_finished, parse_schedule, summarize

from conftest import schedule_doc, schedule_game


def test_is_finished_rules():
    assert is_finished({"codedGameState": "F", "detailedState": "Final"})
    assert is_finished({"codedGameState": "F", "detailedState": "Completed Early"})
    assert not is_finished({"codedGameState": "O", "detailedState": "Game Over"})  # 기록 확정 전
    assert not is_finished({"codedGameState": "S", "detailedState": "Scheduled"})
    assert not is_finished({"codedGameState": "F", "detailedState": "Postponed"})
    assert not is_finished({"codedGameState": "F", "detailedState": "Cancelled"})


def test_parse_schedule_filters_and_dedupes():
    doc = schedule_doc(
        (
            "2026-09-15",
            [
                schedule_game(1, "2026-09-15"),  # Final
                schedule_game(2, "2026-09-15", detailed="Postponed", coded="D"),  # 순연 원래 날짜
                schedule_game(3, "2026-09-15", detailed="Scheduled", coded="S"),
                schedule_game(4, "2026-09-15", detailed="Completed Early", coded="F"),
                schedule_game(5, "2026-09-15", detailed="Cancelled", coded="C"),
            ],
        ),
        ("2026-09-16", [schedule_game(2, "2026-09-16")]),  # 순연 경기 재등장 (같은 gamePk, Final)
    )
    rows = parse_schedule(doc)
    by_pk = {r.game_pk: r for r in rows}

    assert sorted(by_pk) == [1, 2, 3, 4, 5]  # gamePk 당 한 행
    assert by_pk[2].finished and by_pk[2].official_date == "2026-09-16"
    assert {r.game_pk for r in rows if r.finished} == {1, 2, 4}
    assert not by_pk[3].finished and not by_pk[5].finished
    assert by_pk[1].home_team_id == 113 and by_pk[1].away_team_id == 119
    assert summarize(rows) == {"Cancelled": 1, "Completed Early": 1, "Final": 2, "Scheduled": 1}


def test_parse_schedule_keeps_finished_over_later_postponed_entry():
    # Final 항목이 먼저, 같은 pk 의 Postponed 항목이 뒤에 와도 Final 을 유지
    doc = schedule_doc(
        ("2026-09-15", [schedule_game(7, "2026-09-15")]),
        ("2026-09-16", [schedule_game(7, "2026-09-16", detailed="Postponed", coded="D")]),
    )
    (row,) = parse_schedule(doc)
    assert row.finished and row.official_date == "2026-09-15"
