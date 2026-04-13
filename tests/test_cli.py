from pathlib import Path

from typer.testing import CliRunner

from financebuddy.cli import app
from financebuddy.config import load_config
from financebuddy.db import connect


runner = CliRunner()


def test_cli_shows_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "crawl" in result.stdout


def test_crawl_help_mentions_connector_and_saxo_fixture_dir() -> None:
    result = runner.invoke(app, ["crawl", "--help"])

    assert result.exit_code == 0
    assert "demo|saxo" in result.stdout
    assert "tests/fixtures/saxo_bank" in result.stdout
    assert "Saxo owner slug used to build the access" in result.stdout


def test_crawl_command_runs_demo_connector(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--fixture",
            "tests/fixtures/demo_bank/accounts.json",
            "--username",
            "bob",
        ],
        input="secret\n",
    )

    assert result.exit_code == 0
    assert "Main checking" in result.stdout
    assert "VOO" in result.stdout
    assert (tmp_path / "financebuddy.db").exists()
    assert any((tmp_path / "snapshots").glob("*/*.json"))
    row = connect(tmp_path / "financebuddy.db").execute(
        "SELECT profile_id, warnings_json FROM crawl_runs"
    ).fetchone()
    assert row["profile_id"] == "bob-demo-bank"
    assert row["warnings_json"] == "[]"


def test_crawl_command_runs_saxo_connector_with_env_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAXO_ACCESS_TOKEN", "token-123")

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--fixture-dir",
            "tests/fixtures/saxo_bank",
            "--owner",
            "nico",
        ],
    )

    assert result.exit_code == 0
    assert "Saxo Global Account" in result.stdout
    assert "NOVO-B" in result.stdout
    assert (tmp_path / "financebuddy.db").exists()
    assert any((tmp_path / "snapshots").glob("*/*.json"))
    row = connect(tmp_path / "financebuddy.db").execute(
        "SELECT profile_id, connector_id, warnings_json FROM crawl_runs"
    ).fetchone()
    assert row["profile_id"] == "nico-saxo-bank-sim"
    assert row["connector_id"] == "saxo_bank_api"
    assert row["warnings_json"] == "[]"


def test_crawl_command_requires_fixture_dir_before_prompting_for_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)

    def fail_prompt(*args, **kwargs) -> None:
        raise AssertionError(
            "token prompt should not run before fixture-dir validation"
        )

    monkeypatch.setattr("financebuddy.cli.typer.prompt", fail_prompt)

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "fixture",
            "--owner",
            "nico",
        ],
    )

    assert result.exit_code == 2
    assert "--fixture-dir is required for Saxo fixture mode" in result.output


def test_crawl_command_runs_saxo_sim_connector_with_env_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAXO_ACCESS_TOKEN", "token-123")
    called = {"value": False}

    def fake_build_saxo_sim_connector():
        called["value"] = True
        return object()

    monkeypatch.setattr(
        "financebuddy.cli._build_saxo_sim_connector",
        fake_build_saxo_sim_connector,
    )
    monkeypatch.setattr(
        "financebuddy.cli.run_crawl",
        lambda **kwargs: {"accounts": [], "balances": [], "positions": [], "warnings": []},
    )

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "sim",
            "--owner",
            "nico",
        ],
    )

    assert result.exit_code == 0
    assert called["value"] is True


def test_crawl_command_rejects_unsupported_saxo_source(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "invalid",
            "--owner",
            "nico",
        ],
    )

    assert result.exit_code == 2
    assert "--saxo-source must be fixture or sim" in result.output


def test_crawl_command_prompts_for_saxo_access_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--fixture-dir",
            "tests/fixtures/saxo_bank",
            "--owner",
            "nico",
        ],
        input="token-123\n",
    )

    assert result.exit_code == 0
    assert "Saxo Global Account" in result.stdout
    assert "NOVO-B" in result.stdout
    row = connect(tmp_path / "financebuddy.db").execute(
        "SELECT profile_id, connector_id, warnings_json FROM crawl_runs"
    ).fetchone()
    assert row["profile_id"] == "nico-saxo-bank-sim"
    assert row["connector_id"] == "saxo_bank_api"
    assert row["warnings_json"] == "[]"


def test_load_config_uses_default_data_dir() -> None:
    config = load_config()

    assert config.data_dir == Path.cwd() / "data"
    assert config.db_path == Path.cwd() / "data" / "financebuddy.db"
    assert config.snapshot_dir == Path.cwd() / "data" / "snapshots"
    assert config.base_currency == "EUR"


def test_load_config_uses_explicit_root() -> None:
    root = Path("/tmp/financebuddy")
    config = load_config(root)

    assert config.data_dir == root
    assert config.db_path == root / "financebuddy.db"
    assert config.snapshot_dir == root / "snapshots"
    assert config.base_currency == "EUR"
