from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


def load_environment(project_root: Path) -> str:
    """Load profile defaults, then local overrides, preserving process settings."""
    external_keys = set(os.environ)
    base_file = project_root / ".env"
    base_values = dotenv_values(base_file)
    environment = (
                          os.getenv("BOT_ENV") or base_values.get("BOT_ENV") or "development"
                  ).strip().lower() or "development"

    load_dotenv(project_root / f".env.{environment}", override=False)
    for name, value in dotenv_values(base_file).items():
        if name not in external_keys and value is not None:
            os.environ[name] = value
    # A local development selector must not switch a production service's profile.
    os.environ["BOT_ENV"] = environment
    return environment
