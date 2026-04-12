import json
from datetime import UTC, datetime
from pathlib import Path

from financebuddy.models import RawSnapshot
from financebuddy.snapshots import persist_snapshots


def test_persist_snapshots_writes_json_files(tmp_path: Path) -> None:
    snapshots = [
        RawSnapshot(
            snapshot_name="accounts",
            captured_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
            payload={"accounts": [{"id": "acc-1"}]},
        )
    ]

    written_paths = persist_snapshots(tmp_path, "run-123", snapshots)

    assert len(written_paths) == 1
    content = json.loads(written_paths[0].read_text())
    assert content["accounts"][0]["id"] == "acc-1"
