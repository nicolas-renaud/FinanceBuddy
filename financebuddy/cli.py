from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import typer

from financebuddy.config import load_config
from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.connectors.saxo_bank_api import SaxoBankConnector
from financebuddy.services.crawl_runner import run_crawl
from financebuddy.services.reporting import render_summary


app = typer.Typer(help="Local-first finance crawler CLI.")


@app.callback()
def main() -> None:
    """FinanceBuddy CLI."""


@app.command()
def crawl(
    data_dir: Path = typer.Option(..., exists=False),
    connector: str = typer.Option("demo", "--connector"),
    fixture: Path | None = typer.Option(None, exists=True, dir_okay=False),
    fixture_dir: Path | None = typer.Option(None, exists=True, file_okay=False),
    username: str | None = typer.Option(None),
    owner: str | None = typer.Option(None),
    password: str | None = typer.Option(None, hide_input=True),
) -> None:
    """Run a crawl for a configured access profile."""
    config = load_config(data_dir)
    if connector == "demo":
        if fixture is None:
            raise typer.BadParameter("--fixture is required for the demo connector")
        if username is None:
            raise typer.BadParameter("--username is required for the demo connector")
        if password is None:
            password = typer.prompt("Password", hide_input=True)

        connector_impl = DemoBankApiConnector.from_fixture_path(fixture)
        profile = AccessProfile(
            profile_id=f"{username}-demo-bank",
            connector_id="demo_bank_api",
            institution_slug="demo-bank",
            owner_slug=username,
        )
        credentials = RuntimeCredentials(username=username, password=password)
    elif connector == "saxo":
        if fixture_dir is None:
            raise typer.BadParameter(
                "--fixture-dir is required for the Saxo connector"
            )
        if owner is None:
            raise typer.BadParameter("--owner is required for the Saxo connector")

        access_token = os.environ.get("SAXO_ACCESS_TOKEN")
        if not access_token:
            access_token = typer.prompt("Access token", hide_input=True)

        connector_impl = _build_saxo_connector_from_fixture_dir(fixture_dir)
        profile = AccessProfile(
            profile_id=f"{owner}-saxo-bank-sim",
            connector_id="saxo_bank_api",
            institution_slug="saxo-bank",
            owner_slug=owner,
        )
        credentials = RuntimeCredentials(
            username=owner,
            password="",
            access_token=access_token,
        )
    else:
        raise typer.BadParameter(f"Unsupported connector: {connector}")

    outcome = run_crawl(
        db_path=config.db_path,
        snapshot_dir=config.snapshot_dir,
        connector=connector_impl,
        profile=profile,
        credentials=credentials,
    )
    typer.echo(
        render_summary(outcome["accounts"], outcome["balances"], outcome["positions"])
    )


def _build_saxo_connector_from_fixture_dir(fixture_dir: Path) -> SaxoBankConnector:
    responses = _load_saxo_fixture_responses(fixture_dir)
    transport = httpx.MockTransport(
        lambda request: _saxo_fixture_response(request, responses)
    )
    client = httpx.Client(
        transport=transport,
        base_url="https://api.saxo.example",
    )
    return SaxoBankConnector(client=client)


def _load_saxo_fixture_responses(fixture_dir: Path) -> dict[str, dict[str, Any]]:
    responses: dict[str, dict[str, Any]] = {}

    for fixture_path in sorted(fixture_dir.glob("accounts_page_*.json")):
        page_number = int(fixture_path.stem.split("_")[-1])
        route = "/port/v1/accounts" if page_number == 1 else f"/port/v1/accounts?page={page_number}"
        responses[route] = json.loads(fixture_path.read_text())

    for fixture_path in sorted(fixture_dir.glob("balance_*.json")):
        payload = json.loads(fixture_path.read_text())
        account_key = payload["AccountKey"]
        responses[f"/port/v1/accounts/{account_key}/balance"] = payload

    positions_path = fixture_dir / "positions.json"
    if positions_path.exists():
        responses["/port/v1/positions"] = json.loads(positions_path.read_text())

    return responses


def _saxo_fixture_response(
    request: httpx.Request,
    responses: dict[str, dict[str, Any]],
) -> httpx.Response:
    route = request.url.raw_path.decode()
    payload = responses.get(route)
    if payload is None:
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.Response(
        200,
        json=payload,
        headers={"content-type": "application/json"},
    )
