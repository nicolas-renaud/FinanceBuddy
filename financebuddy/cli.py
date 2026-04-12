from __future__ import annotations

from pathlib import Path

import typer

from financebuddy.config import load_config
from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.services.crawl_runner import run_crawl
from financebuddy.services.reporting import render_summary


app = typer.Typer(help="Local-first finance crawler CLI.")


@app.callback()
def main() -> None:
    """FinanceBuddy CLI."""


@app.command()
def crawl(
    data_dir: Path = typer.Option(..., exists=False),
    fixture: Path = typer.Option(..., exists=True, dir_okay=False),
    username: str = typer.Option(...),
    password: str | None = typer.Option(None, hide_input=True),
) -> None:
    """Run a crawl for a configured access profile."""
    if password is None:
        password = typer.prompt("Password", hide_input=True)

    config = load_config(data_dir)
    connector = DemoBankApiConnector.from_fixture_path(fixture)
    profile = AccessProfile(
        profile_id=f"{username}-demo-bank",
        connector_id="demo_bank_api",
        institution_slug="demo-bank",
        owner_slug=username,
    )
    credentials = RuntimeCredentials(username=username, password=password)

    outcome = run_crawl(
        db_path=config.db_path,
        snapshot_dir=config.snapshot_dir,
        connector=connector,
        profile=profile,
        credentials=credentials,
    )
    typer.echo(
        render_summary(outcome["accounts"], outcome["balances"], outcome["positions"])
    )
