from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from bigness_league_bot.core.settings import PROJECT_ROOT

LOGGER = logging.getLogger("bigness_league_bot.activity")
SOURCE_CATALOG = PROJECT_ROOT / "aa_resources" / "team_logos" / "sources.json"
DISCORD_ATTACHMENT_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}
_DRIVE_FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,200}\Z")


def is_discord_attachment(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.hostname in DISCORD_ATTACHMENT_HOSTS and parsed.path.startswith("/attachments/")


def resolve_team_logo_source(url: str, *, catalog_path: Path = SOURCE_CATALOG) -> str:
    """Resolve Drive viewer links and explicitly recovered Discord attachments.

    Recovery matches an attachment path, never a filename or a team name. A new
    Sheets URL therefore cannot accidentally select an earlier team's logo.
    """
    parsed = urlsplit(url)
    if parsed.hostname == "drive.google.com":
        query = parse_qs(parsed.query)
        match = re.fullmatch(r"/file/d/([A-Za-z0-9_-]+)(?:/view|/preview)?/?", parsed.path)
        file_id = match.group(1) if match else None
        if parsed.path in ("/open", "/uc"):
            file_id = query.get("id", [None])[0]
        if file_id and _DRIVE_FILE_ID.fullmatch(file_id):
            resource_key = query.get("resourcekey", [None])[0]
            return _drive_download_url(file_id, resource_key=resource_key)
    if is_discord_attachment(url):
        file_id = _recovered_drive_file_id(parsed.path, catalog_path)
        if file_id is not None:
            LOGGER.info("TEAM_LOGO_SOURCE_RECOVERED path=%s provider=google_drive", parsed.path)
            return _drive_download_url(file_id)
    return url


def _drive_download_url(file_id: str, *, resource_key: str | None = None) -> str:
    parameters = {"export": "download", "id": file_id}
    if resource_key:
        parameters["resourcekey"] = resource_key
    return "https://drive.google.com/uc?" + urlencode(parameters)


def _recovered_drive_file_id(attachment_path: str, catalog_path: Path) -> str | None:
    try:
        # Keep this deployable catalog small and declarative; no Drive scraping
        # or credential loading is performed in the announcement path.
        with catalog_path.open("r", encoding="utf-8") as source:
            entries = json.loads(source.read(65_537))
        if not isinstance(entries, list) or len(entries) > 256:
            raise ValueError("invalid_catalog")
        matches = [entry["drive_file_id"] for entry in entries
                   if entry["discord_attachment_path"] == attachment_path]
        if len(matches) > 1 or any(not _DRIVE_FILE_ID.fullmatch(value) for value in matches):
            raise ValueError("invalid_mapping")
        return matches[0] if matches else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        LOGGER.warning("TEAM_LOGO_SOURCE_CATALOG_INVALID")
        return None
