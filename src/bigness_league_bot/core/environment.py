from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


def load_environment(project_root: Path) -> str:
    """Load the selected profile and private local settings.

    Development uses local values ahead of inherited process values to keep
    IDE launches tied to this checkout's credentials. Production preserves
    explicit process settings supplied by the deployment environment.
    BOT_ENV from the process always selects the profile.
    """
    external_keys = set(os.environ)
    base_file = project_root / ".env"
    base_values = dotenv_values(base_file)
    environment = (
                          os.getenv("BOT_ENV") or base_values.get("BOT_ENV") or "development"
                  ).strip().lower() or "development"

    load_dotenv(project_root / f".env.{environment}", override=False)
    for name, value in dotenv_values(base_file).items():
        if value is not None and (environment == "development" or name not in external_keys):
            os.environ[name] = value
    # A local development selector must not switch a production service's profile.
    os.environ["BOT_ENV"] = environment
    return environment
