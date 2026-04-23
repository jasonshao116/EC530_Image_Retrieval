"""Local configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | str = ".env") -> None:
    """Load simple KEY=VALUE pairs from a local .env file.

    Existing environment variables win, so shell exports and deployment
    settings can override local development defaults.
    """

    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key or key in os.environ:
            continue

        os.environ[key] = value
