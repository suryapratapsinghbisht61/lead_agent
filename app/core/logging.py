"""One logging setup for CLI, worker and API: readable console lines + a log file."""

import logging
from pathlib import Path

from app.core.config import ROOT_DIR


def setup_logging(level: str = "INFO", log_file: Path = ROOT_DIR / "logs" / "agent.log") -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )
    # These libraries are very chatty at INFO level.
    for noisy in ("httpx", "httpcore", "urllib3", "brightdata", "google_genai", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
