from typer.testing import CliRunner

from financebuddy.cli import app


runner = CliRunner()


def test_cli_shows_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Commands" in result.stdout
    assert "crawl" in result.stdout


def test_cli_crawl_executes_placeholder() -> None:
    result = runner.invoke(app, ["crawl"])

    assert result.exit_code == 0
    assert "crawl not implemented yet" in result.stdout
