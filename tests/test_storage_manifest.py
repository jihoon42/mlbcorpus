import gzip

from mlbcorpus.manifest import Manifest
from mlbcorpus.storage import read_gz_bytes, read_gz_json, write_gz_atomic

from conftest import schedule_doc, schedule_game
from mlbcorpus.schedule import parse_schedule

RESOURCES = ("feed", "content.en", "content.es", "winprob")


def test_write_gz_atomic_roundtrip(tmp_path):
    path = tmp_path / "a" / "b" / "x.json.gz"
    payload = b'{"k": "\xed\x95\x9c\xea\xb8\x80"}'  # 한글 UTF-8 바이트도 그대로
    size = write_gz_atomic(path, payload)
    assert path.exists() and size == path.stat().st_size
    assert not path.with_name("x.json.gz.tmp").exists()
    assert read_gz_bytes(path) == payload
    assert read_gz_json(path) == {"k": "한글"}
    with gzip.open(path, "rb") as f:  # 표준 gzip 으로도 열린다
        assert f.read() == payload


def _manifest_with_games(path):
    manifest = Manifest(path)
    rows = parse_schedule(
        schedule_doc(
            (
                "2026-09-15",
                [
                    schedule_game(1, "2026-09-15"),
                    schedule_game(2, "2026-09-15"),
                    schedule_game(3, "2026-09-15", detailed="Scheduled", coded="S"),
                    schedule_game(4, "2026-09-15", season=2025, game_type="W"),
                ],
            )
        )
    )
    manifest.upsert_games(rows)
    return manifest


def test_manifest_pending_and_resume(tmp_path):
    with _manifest_with_games(tmp_path / "m.sqlite") as m:
        pending = m.pending(RESOURCES)
        assert [(p.game_pk, p.missing) for p in pending] == [(4, RESOURCES), (1, RESOURCES), (2, RESOURCES)]

        m.mark(1, "feed", ok=True, nbytes=10)
        m.mark(1, "content.en", ok=False, error="HTTP 500")
        pending = {p.game_pk: p.missing for p in m.pending(RESOURCES)}
        assert pending[1] == ("content.en", "content.es", "winprob")  # 실패한 건 다시 대상

        for r in RESOURCES:
            m.mark(1, r, ok=True, nbytes=1)
        assert {p.game_pk for p in m.pending(RESOURCES)} == {2, 4}
        assert {p.game_pk for p in m.pending(RESOURCES, force=True)} == {1, 2, 4}
        assert {p.game_pk for p in m.pending(RESOURCES, seasons=[2026])} == {2}
        assert {p.game_pk for p in m.pending(RESOURCES, game_types=["W"])} == {4}


def test_manifest_upsert_updates_status(tmp_path):
    with _manifest_with_games(tmp_path / "m.sqlite") as m:
        assert {p.game_pk for p in m.pending(RESOURCES)} == {1, 2, 4}
        # 3번 경기가 다음 실행에서 Final 로 바뀜
        m.upsert_games(parse_schedule(schedule_doc(("2026-09-15", [schedule_game(3, "2026-09-15")]))))
        assert {p.game_pk for p in m.pending(RESOURCES)} == {1, 2, 3, 4}


def test_manifest_summary(tmp_path):
    with _manifest_with_games(tmp_path / "m.sqlite") as m:
        for r in RESOURCES:
            m.mark(1, r, ok=True, nbytes=100)
        m.mark(2, "feed", ok=True, nbytes=50)
        m.mark(2, "winprob", ok=False, error="x")
        s = m.summary(RESOURCES)
        assert s["games_by_status"] == {"Final": 3, "Scheduled": 1}
        assert s["finished_games"] == 3 and s["complete_games"] == 1
        assert s["per_resource_ok"] == {"content.en": 1, "content.es": 1, "feed": 2, "winprob": 1}
        assert s["failed_fetches"] == 1 and s["stored_bytes"] == 450
        assert s["finished_by_season"] == [
            {"season": 2025, "game_type": "W", "finished": 1},
            {"season": 2026, "game_type": "R", "finished": 2},
        ]
        assert m.recent_errors()[0][:2] == (2, "winprob")
