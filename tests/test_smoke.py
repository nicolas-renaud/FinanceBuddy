from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from financebuddy.cli import app
from financebuddy.db import connect


runner = CliRunner()


def test_smoke_runs_saxo_fixture_crawl(
    tmp_path: Path, monkeypatch
) -> None:
    access_token = os.environ.get("SAXO_ACCESS_TOKEN")
    input_text = None

    if access_token:
        monkeypatch.setenv("SAXO_ACCESS_TOKEN", access_token)
    else:
        input_text = "token-123\n"

    result = runner.invoke(
        app,
        [
            "crawl",
            "--connector",
            "saxo",
            "--data-dir",
            str(tmp_path),
            "--owner",
            "nico",
            "--fixture-dir",
            "tests/fixtures/saxo_bank",
        ],
        input=input_text,
    )

    assert result.exit_code == 0
    assert "Saxo Global Account" in result.stdout
    assert "Position: NOVO-B qty=12.5 price=987.40 DKK" in result.stdout
    assert (tmp_path / "financebuddy.db").exists()

    snapshot_files = sorted((tmp_path / "snapshots").glob("*/*.json"))
    assert snapshot_files
    assert all(path.is_file() for path in snapshot_files)

    with connect(tmp_path / "financebuddy.db") as connection:
        crawl_run = connection.execute(
            """
            SELECT profile_id, connector_id, status
            FROM crawl_runs
            """
        ).fetchone()
        assert crawl_run["profile_id"] == "nico-saxo-bank-sim"
        assert crawl_run["connector_id"] == "saxo_bank_api"
        assert crawl_run["status"] == "success"

        position_row = connection.execute(
            """
            SELECT canonical_account_key, asset_key, quantity, unit_price, currency
            FROM current_positions
            WHERE canonical_account_key = ? AND asset_key = ?
            """,
            ("account:ACC-001", "asset:NOVO-B"),
        ).fetchone()
        assert position_row["canonical_account_key"] == "account:ACC-001"
        assert position_row["asset_key"] == "asset:NOVO-B"
        assert position_row["quantity"] == "12.5"
        assert position_row["unit_price"] == "987.40"
        assert position_row["currency"] == "DKK"
