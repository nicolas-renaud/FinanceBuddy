from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    snapshot_dir: Path
    base_currency: str = "EUR"


def load_config(root: Path | None = None) -> AppConfig:
    base_dir = root or Path.cwd() / "data"
    return AppConfig(
        data_dir=base_dir,
        db_path=base_dir / "financebuddy.db",
        snapshot_dir=base_dir / "snapshots",
    )
