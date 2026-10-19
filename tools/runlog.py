"""Capture the run's log and write it, with a JSON summary, to LOG_DIR.

On the server LOG_DIR is a host folder served by nginx, so the last run is
always available at http://<server>/runs/latest.log (and latest.json).
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
KEEP_RUNS = 30  # timestamped copies kept per file type


class RunLog:
    def __init__(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self._buffer = io.StringIO()
        self._handler = logging.StreamHandler(self._buffer)
        self._handler.setFormatter(logging.Formatter(LOG_FORMAT))

    def attach(self, logger: logging.Logger) -> None:
        logger.addHandler(self._handler)

    def write(self, log_dir: Path, summary: dict[str, Any]) -> Path:
        """Write <stamp>.log/.json plus latest.log/.json; returns the latest.log path."""
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        summary_text = json.dumps(
            {"started_at": self.started_at.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), **summary},
            indent=2,
        )
        log_text = self._buffer.getvalue()
        for name, text in ((f"{stamp}.log", log_text), (f"{stamp}.json", summary_text),
                           ("latest.log", log_text), ("latest.json", summary_text)):
            (log_dir / name).write_text(text, encoding="utf-8", newline="\n")
        for pattern in ("2*.log", "2*.json"):  # prune old timestamped copies
            for old in sorted(log_dir.glob(pattern))[:-KEEP_RUNS]:
                old.unlink()
        return log_dir / "latest.log"
