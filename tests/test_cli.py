from pathlib import Path
from types import SimpleNamespace
from typing import Any

from typer.testing import CliRunner

from financebuddy.auth.saxo_oauth import SaxoOAuthError
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
    assert "--fixture-dir" in result.stdout
    assert "--owner" in result.stdout


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


def test_crawl_command_ignores_saxo_source_for_demo_connector(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "demo",
            "--saxo-source",
            "invalid",
            "--fixture",
            "tests/fixtures/demo_bank/accounts.json",
            "--username",
            "bob",
        ],
        input="secret\n",
    )

    assert result.exit_code == 0
    assert "Main checking" in result.stdout
    row = connect(tmp_path / "financebuddy.db").execute(
        "SELECT profile_id, connector_id FROM crawl_runs"
    ).fetchone()
    assert row["profile_id"] == "bob-demo-bank"
    assert row["connector_id"] == "demo_bank_api"


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


def test_saxo_auth_login_command_saves_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAXO_APP_KEY", "app-key")
    saved: dict[str, Any] = {}

    class FakeFileTokenStore:
        def __init__(self, data_dir: Path) -> None:
            saved["data_dir"] = data_dir

        def save(self, profile_id: str, token_set: object) -> None:
            saved["token"] = (profile_id, token_set.access_token)

    fake_token = SimpleNamespace(access_token="access-from-login")

    monkeypatch.setattr("financebuddy.cli.FileTokenStore", FakeFileTokenStore)
    monkeypatch.setattr(
        "financebuddy.cli.SaxoOAuthClient",
        lambda *, app_key: SimpleNamespace(app_key=app_key),
    )
    monkeypatch.setattr(
        "financebuddy.cli.run_interactive_pkce_login",
        lambda **kwargs: fake_token,
    )

    result = runner.invoke(
        app,
        [
            "saxo-auth",
            "login",
            "--data-dir",
            str(tmp_path),
            "--owner",
            "nico",
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 0
    assert saved["data_dir"] == tmp_path
    assert saved["token"] == ("nico-saxo-bank-sim", "access-from-login")
    assert "Saxo authorization saved for nico-saxo-bank-sim" in result.stdout


def test_saxo_auth_login_command_reports_oauth_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAXO_APP_KEY", "app-key")
    monkeypatch.setattr(
        "financebuddy.cli.SaxoOAuthClient",
        lambda *, app_key: SimpleNamespace(app_key=app_key),
    )

    def fail_login(**kwargs: Any) -> object:
        raise SaxoOAuthError("boom")

    monkeypatch.setattr("financebuddy.cli.run_interactive_pkce_login", fail_login)

    result = runner.invoke(
        app,
        [
            "saxo-auth",
            "login",
            "--data-dir",
            str(tmp_path),
            "--owner",
            "nico",
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 2
    assert "boom" in result.output
    assert "Traceback" not in result.output


def test_saxo_sim_crawl_uses_token_resolver_when_env_token_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("SAXO_APP_KEY", "app-key")
    captured: dict[str, Any] = {}

    class FakeSaxoTokenResolver:
        def __init__(self, **kwargs: Any) -> None:
            captured["resolver_init"] = kwargs

        def resolve_access_token(self, **kwargs: Any) -> str:
            captured["resolve"] = kwargs
            return "resolved-token"

    monkeypatch.setattr("financebuddy.cli.SaxoTokenResolver", FakeSaxoTokenResolver)
    monkeypatch.setattr(
        "financebuddy.cli.FileTokenStore",
        lambda data_dir: SimpleNamespace(data_dir=data_dir),
    )
    monkeypatch.setattr(
        "financebuddy.cli.SaxoOAuthClient",
        lambda *, app_key: SimpleNamespace(app_key=app_key),
    )
    monkeypatch.setattr(
        "financebuddy.cli.run_interactive_pkce_login",
        lambda **kwargs: SimpleNamespace(access_token="unused"),
    )
    monkeypatch.setattr("financebuddy.cli._build_saxo_sim_connector", lambda: object())

    def fake_run_crawl(**kwargs: Any) -> dict[str, list[object]]:
        captured["credentials"] = kwargs["credentials"]
        return {"accounts": [], "balances": [], "positions": [], "warnings": []}

    monkeypatch.setattr("financebuddy.cli.run_crawl", fake_run_crawl)

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
    assert captured["resolve"] == {
        "profile_id": "nico-saxo-bank-sim",
        "access_token_override": None,
        "allow_interactive_login": True,
    }
    assert captured["credentials"].access_token == "resolved-token"


def test_saxo_sim_crawl_passes_env_token_override_to_token_resolver(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAXO_ACCESS_TOKEN", "token-123")
    monkeypatch.delenv("SAXO_APP_KEY", raising=False)
    captured: dict[str, Any] = {}

    class FakeSaxoTokenResolver:
        def __init__(self, **kwargs: Any) -> None:
            captured["resolver_init"] = kwargs

        def resolve_access_token(self, **kwargs: Any) -> str:
            captured["resolve"] = kwargs
            return "token-123"

    monkeypatch.setattr("financebuddy.cli.SaxoTokenResolver", FakeSaxoTokenResolver)
    monkeypatch.setattr(
        "financebuddy.cli.FileTokenStore",
        lambda data_dir: SimpleNamespace(data_dir=data_dir),
    )
    monkeypatch.setattr(
        "financebuddy.cli.SaxoOAuthClient",
        lambda *, app_key: SimpleNamespace(app_key=app_key),
    )
    monkeypatch.setattr(
        "financebuddy.cli.run_interactive_pkce_login",
        lambda **kwargs: SimpleNamespace(access_token="unused"),
    )
    monkeypatch.setattr("financebuddy.cli._build_saxo_sim_connector", lambda: object())

    def fake_run_crawl(**kwargs: Any) -> dict[str, list[object]]:
        captured["credentials"] = kwargs["credentials"]
        return {"accounts": [], "balances": [], "positions": [], "warnings": []}

    monkeypatch.setattr("financebuddy.cli.run_crawl", fake_run_crawl)

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
    assert captured["resolve"] == {
        "profile_id": "nico-saxo-bank-sim",
        "access_token_override": "token-123",
        "allow_interactive_login": True,
    }
    assert captured["credentials"].access_token == "token-123"


def test_saxo_sim_crawl_no_auth_login_disables_interactive_login(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("SAXO_APP_KEY", "app-key")
    captured: dict[str, Any] = {}

    class FakeSaxoTokenResolver:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def resolve_access_token(self, **kwargs: Any) -> str:
            captured["resolve"] = kwargs
            return "resolved-token"

    monkeypatch.setattr("financebuddy.cli.SaxoTokenResolver", FakeSaxoTokenResolver)
    monkeypatch.setattr(
        "financebuddy.cli.FileTokenStore",
        lambda data_dir: SimpleNamespace(data_dir=data_dir),
    )
    monkeypatch.setattr(
        "financebuddy.cli.SaxoOAuthClient",
        lambda *, app_key: SimpleNamespace(app_key=app_key),
    )
    monkeypatch.setattr(
        "financebuddy.cli.run_interactive_pkce_login",
        lambda **kwargs: SimpleNamespace(access_token="unused"),
    )
    monkeypatch.setattr("financebuddy.cli._build_saxo_sim_connector", lambda: object())
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
            "--no-auth-login",
        ],
    )

    assert result.exit_code == 0
    assert captured["resolve"]["allow_interactive_login"] is False


def test_saxo_sim_crawl_requires_app_key_without_env_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SAXO_APP_KEY", raising=False)

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
            "--no-auth-login",
        ],
    )

    assert result.exit_code == 2
    assert "SAXO_APP_KEY is required" in result.output


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
