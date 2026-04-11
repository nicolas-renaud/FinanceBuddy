from __future__ import annotations

import typer
import click


def _make_metavar_compat(self, ctx=None) -> str:
    if self.metavar is not None:
        return self.metavar

    metavar = self.type.get_metavar(param=self, ctx=ctx) if ctx is not None else None
    if metavar is None:
        metavar = self.type.name.upper()

    if self.nargs != 1:
        metavar += "..."

    return metavar


click.core.Parameter.make_metavar = _make_metavar_compat


app = typer.Typer(help="Local-first finance crawler CLI.")


@app.command()
def crawl() -> None:
    """Run a crawl for a configured access profile."""
    typer.echo("crawl not implemented yet")
