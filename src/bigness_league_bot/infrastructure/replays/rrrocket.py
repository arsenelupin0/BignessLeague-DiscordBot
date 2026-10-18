"""Read replay header names using the external rrrocket / Boxcars parser."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import unicodedata

from bigness_league_bot.application.services.match_replay_names import ReplayAccountName

MAX_REPLAY_BYTES = 32 * 1024 * 1024
MAX_HEADER_JSON_BYTES = 8 * 1024 * 1024
PLATFORMS = {
    "OnlinePlatform_Epic": "epic", "OnlinePlatform_Steam": "steam",
    "OnlinePlatform_PS4": "psn", "OnlinePlatform_PS5": "psn",
    "OnlinePlatform_Dingo": "xbl", "OnlinePlatform_Switch": "switch",
}


class ReplayNameParserError(Exception):
    def __init__(self, reason: str, details: str = "") -> None:
        self.reason = reason
        self.details = details
        super().__init__(reason)


class RrrocketNameReader:
    def __init__(self, executable: Path, *, timeout_seconds: int = 10) -> None:
        if not 1 <= timeout_seconds <= 60:
            raise ValueError("El timeout del parser debe estar entre 1 y 60 segundos.")
        self.executable = executable.resolve()
        self.timeout_seconds = timeout_seconds

    def read_names(self, content: bytes) -> tuple[ReplayAccountName, ...]:
        if not content or len(content) > MAX_REPLAY_BYTES:
            raise ReplayNameParserError("input_size")
        try:
            # No filename or shell interpolation. rrrocket reads the original
            # bytes from stdin and skips the patch-sensitive network stream.
            result = subprocess.run(
                [str(self.executable), "--crc-check"], input=content, capture_output=True,
                timeout=self.timeout_seconds, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ReplayNameParserError("timeout") from exc
        except OSError as exc:
            raise ReplayNameParserError("executable_unavailable", str(exc)) from exc
        if result.returncode:
            details = result.stderr.decode("utf-8", errors="replace").strip()[:500]
            raise ReplayNameParserError("parser_exit", details)
        if len(result.stdout) > MAX_HEADER_JSON_BYTES:
            raise ReplayNameParserError("output_size")
        try:
            payload = json.loads(result.stdout)
        except (ValueError, UnicodeError) as exc:
            raise ReplayNameParserError("invalid_json") from exc
        return extract_header_account_names(payload)


def extract_header_account_names(payload: Any) -> tuple[ReplayAccountName, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("properties"), dict):
        raise ReplayNameParserError("invalid_header")
    players = payload["properties"].get("PlayerStats")
    if not isinstance(players, list):
        raise ReplayNameParserError("missing_player_stats")
    names = []
    for player in players:
        if (not isinstance(player, dict) or player.get("bBot")
                or type(player.get("Team")) is not int or player.get("Team") not in (0, 1)):
            continue
        platform_value = player.get("Platform", {})
        platform_key = platform_value.get("value") if isinstance(platform_value, dict) else None
        platform = PLATFORMS.get(platform_key) if isinstance(platform_key, str) else None
        name = player.get("Name")
        if not platform or not isinstance(name, str) or not _valid_name(name):
            continue
        player_id = player.get("PlayerID", {})
        fields = player_id.get("fields", {}) if isinstance(player_id, dict) else {}
        if not isinstance(fields, dict):
            continue
        if platform == "epic":
            identity = _identifier(fields.get("EpicAccountId"))
        else:
            # On consoles OnlineID can be a numeric ID while the analyzer uses
            # a gamertag. Keep the actual ID; a differing identity won't join.
            identity = _identifier(player.get("OnlineID")) or _identifier(fields.get("Uid"))
        if identity:
            names.append(ReplayAccountName(platform, identity, name))
    return tuple(names)


def _identifier(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    value = str(value).strip()
    return value if value and set(value) != {"0"} else ""


def _valid_name(name: str) -> bool:
    return bool(name.strip()) and "\ufffd" not in name and not any(
        unicodedata.category(character) in {"Cc", "Cs"} for character in name
    )
