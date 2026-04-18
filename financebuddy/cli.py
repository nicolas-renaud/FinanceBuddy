from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import typer

from financebuddy.auth.saxo_oauth import (
    SaxoOAuthClient,
    SaxoOAuthError,
    SaxoTokenResolver,
    run_interactive_pkce_login,
)
from financebuddy.auth.token_store import FileTokenStore
from financebuddy.config import load_config
from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.connectors.saxo_bank_api import SaxoBankConnector
from financebuddy.services.crawl_runner import run_crawl
from financebuddy.services.reporting import render_summary


app = typer.Typer(help="Local-first finance crawler CLI.")
saxo_auth_app = typer.Typer(help="Saxo authentication commands.")
app.add_typer(saxo_auth_app, name="saxo-auth")


@app.callback()
def main() -> None:
    """FinanceBuddy CLI."""


@app.command()
def crawl(
    data_dir: Path = typer.Option(..., exists=False),
    connector: str = typer.Option(
        "demo",
        "--connector",
        help="Connector to run: demo|saxo.",
    ),
    fixture: Path | None = typer.Option(
        None,
        exists=True,
        dir_okay=False,
        help="Demo fixture JSON for --connector demo.",
    ),
    fixture_dir: Path | None = typer.Option(
        None,
        exists=True,
        file_okay=False,
        help="Saxo fixture directory, e.g. tests/fixtures/saxo_bank.",
    ),
    saxo_source: str = typer.Option(
        "fixture",
        "--saxo-source",
        help="Saxo source to use: fixture|sim.",
    ),
    username: str | None = typer.Option(
        None,
        help="Demo username used to build the access profile owner.",
    ),
    owner: str | None = typer.Option(
        None,
        help="Saxo owner slug used to build the access profile.",
    ),
    password: str | None = typer.Option(
        None,
        hide_input=True,
        help="Demo password; prompted interactively if omitted.",
    ),
    saxo_app_key: str | None = typer.Option(
        None,
        "--saxo-app-key",
        help="Saxo OpenAPI app key. Defaults to SAXO_APP_KEY.",
    ),
    auth_login: bool = typer.Option(
        True,
        "--auth-login/--no-auth-login",
        help="Allow interactive Saxo OAuth login when no usable refresh token exists.",
    ),
    saxo_auth_port: int = typer.Option(
        8765,
        "--saxo-auth-port",
        help="Localhost port for Saxo OAuth callback.",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-open-browser",
        help="Open the Saxo OAuth URL in the default browser.",
    ),
) -> None:
    """Run a crawl for a demo or Saxo access profile."""
    config = load_config(data_dir)
    if saxo_source not in {"fixture", "sim"}:
        raise typer.BadParameter("--saxo-source must be fixture or sim")

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
        if owner is None:
            raise typer.BadParameter("--owner is required for the Saxo connector")

        profile = AccessProfile(
            profile_id=f"{owner}-saxo-bank-sim",
            connector_id="saxo_bank_api",
            institution_slug="saxo-bank",
            owner_slug=owner,
        )
        access_token_override = os.environ.get("SAXO_ACCESS_TOKEN")

        if saxo_source == "fixture":
            if fixture_dir is None:
                raise typer.BadParameter(
                    "--fixture-dir is required for Saxo fixture mode"
                )
            connector_impl = _build_saxo_connector_from_fixture_dir(fixture_dir)
            access_token = access_token_override
            if not access_token:
                access_token = typer.prompt("Access token", hide_input=True)
        else:
            connector_impl = _build_saxo_sim_connector()
            access_token = _resolve_saxo_sim_access_token(
                data_dir=config.data_dir,
                profile_id=profile.profile_id,
                app_key=saxo_app_key or os.environ.get("SAXO_APP_KEY"),
                access_token_override=access_token_override,
                allow_interactive_login=auth_login,
                auth_port=saxo_auth_port,
                open_browser=open_browser,
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
        render_summary(
            outcome["accounts"],
            outcome["balances"],
            outcome["positions"],
            base_currency=config.base_currency,
        )
    )


@saxo_auth_app.command("login")
def saxo_auth_login(
    data_dir: Path = typer.Option(..., exists=False),
    owner: str = typer.Option(
        ...,
        "--owner",
        help="Saxo owner slug used to build the access profile.",
    ),
    saxo_app_key: str | None = typer.Option(
        None,
        "--saxo-app-key",
        help="Saxo OpenAPI app key. Defaults to SAXO_APP_KEY.",
    ),
    saxo_auth_port: int = typer.Option(
        8765,
        "--saxo-auth-port",
        help="Localhost port for Saxo OAuth callback.",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-open-browser",
        help="Open the Saxo OAuth URL in the default browser.",
    ),
) -> None:
    """Run interactive Saxo OAuth login and save the token set."""
    config = load_config(data_dir)
    profile_id = f"{owner}-saxo-bank-sim"
    app_key = saxo_app_key or os.environ.get("SAXO_APP_KEY")
    if not app_key:
        raise typer.BadParameter("SAXO_APP_KEY is required for Saxo OAuth login")

    oauth_client = SaxoOAuthClient(app_key=app_key)
    try:
        try:
            token_set = run_interactive_pkce_login(
                app_key=app_key,
                oauth_client=oauth_client,
                port=saxo_auth_port,
                open_browser=open_browser,
                echo=typer.echo,
            )
            FileTokenStore(config.data_dir).save(profile_id, token_set)
        except SaxoOAuthError as exc:
            raise typer.BadParameter(str(exc)) from exc
    finally:
        _close_if_supported(oauth_client)

    typer.echo(f"Saxo authorization saved for {profile_id}")


def _resolve_saxo_sim_access_token(
    *,
    data_dir: Path,
    profile_id: str,
    app_key: str | None,
    access_token_override: str | None,
    allow_interactive_login: bool,
    auth_port: int,
    open_browser: bool,
) -> str:
    effective_app_key = app_key or ""
    if not access_token_override and not effective_app_key:
        raise typer.BadParameter("SAXO_APP_KEY is required for Saxo OAuth login")

    oauth_client = SaxoOAuthClient(app_key=effective_app_key)
    try:
        resolver = SaxoTokenResolver(
            app_key=effective_app_key,
            store=FileTokenStore(data_dir),
            oauth_client=oauth_client,
            interactive_login=lambda: run_interactive_pkce_login(
                app_key=effective_app_key,
                oauth_client=oauth_client,
                port=auth_port,
                open_browser=open_browser,
                echo=typer.echo,
            ),
        )
        try:
            return resolver.resolve_access_token(
                profile_id=profile_id,
                access_token_override=access_token_override,
                allow_interactive_login=allow_interactive_login,
            )
        except SaxoOAuthError as exc:
            raise typer.BadParameter(str(exc)) from exc
    finally:
        _close_if_supported(oauth_client)


def _close_if_supported(client: object) -> None:
    close = getattr(client, "close", None)
    if close is not None:
        close()


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


def _build_saxo_sim_connector() -> SaxoBankConnector:
    base_url = "https://gateway.saxobank.com/sim/openapi"
    client = httpx.Client(base_url=base_url)
    return SaxoBankConnector(client=client, base_url=base_url)


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
