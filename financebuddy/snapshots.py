from __future__ import annotations

import json
from pathlib import Path

from financebuddy.models import RawSnapshot


def persist_snapshots(
    snapshot_root: Path,
    run_id: str,
    snapshots: list[RawSnapshot],
) -> list[Path]:
    run_dir = snapshot_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    for snapshot in snapshots:
        snapshot_path = Path(snapshot.snapshot_name)
        if snapshot_path.name != snapshot.snapshot_name or snapshot.snapshot_name in {"", ".", ".."}:
            raise ValueError("snapshot_name must be a single safe filename segment")

        path = run_dir / f"{snapshot.snapshot_name}.json"
        path.write_text(
            json.dumps(snapshot.payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        written_paths.append(path)

    return written_paths
