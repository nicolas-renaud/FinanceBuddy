from pathlib import Path

from typer.testing import CliRunner

from financebuddy.cli import app
from financebuddy.config import load_config


runner = CliRunner()


def test_cli_shows_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "crawl" in result.stdout


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
            "alice",
            "--password",
            "secret",
        ],
    )

    assert result.exit_code == 0
    assert "Main checking" in result.stdout
    assert "VOO" in result.stdout


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
