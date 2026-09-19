import pytest

from mlbcorpus import cli


def test_parse_seasons():
    assert cli.parse_seasons("2019-2021,2025") == (2019, 2020, 2021, 2025)
    assert cli.parse_seasons("2024") == (2024,)
    assert cli.parse_seasons("2025,2024,2025") == (2024, 2025)


def test_parse_csv():
    assert cli.parse_csv("R, F ,D") == ("R", "F", "D")


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("crawl", "status", "sample", "meta", "build-tables"):
        assert cmd in out


def test_status_without_manifest(tmp_path, capsys):
    assert cli.main(["--data-dir", str(tmp_path / "data"), "status"]) == 1
    assert "manifest 없음" in capsys.readouterr().out


def test_build_tables_not_implemented(tmp_path, capsys):
    assert cli.main(["--data-dir", str(tmp_path / "data"), "build-tables"]) == 2
    assert "아직 구현되지" in capsys.readouterr().err


def test_make_settings_overrides(tmp_path):
    args = cli.build_parser().parse_args(
        ["--data-dir", str(tmp_path), "crawl", "--rps", "1.5", "--concurrency", "2", "--languages", "en"]
    )
    settings = cli.make_settings(args)
    assert settings.requests_per_second == 1.5 and settings.concurrency == 2
    assert settings.languages == ("en",)
    assert settings.resource_names() == ("feed", "content.en", "winprob")
    assert args.seasons == tuple(range(2019, 2027)) and args.game_types == ("R", "F", "D", "L", "W")
