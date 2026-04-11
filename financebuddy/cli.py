from __future__ import annotations

import typer


app = typer.Typer(help="Local-first finance crawler CLI.")


@app.command()
def crawl() -> None:
    """Run a crawl for a configured access profile."""
    typer.echo("crawl not implemented yet")
