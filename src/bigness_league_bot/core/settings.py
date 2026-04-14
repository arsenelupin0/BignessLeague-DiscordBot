#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from bigness_league_bot.core.timezones import resolve_timezone

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{name} debe ser un booleano valido.")


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        return int(raw_value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} debe ser un entero valido.") from exc


def _read_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _read_optional_str(name: str) -> str | None:
    raw_value = os.getenv(name)
    if raw_value is None:
        return None

    normalized_value = raw_value.strip()
    return normalized_value or None


def _resolve_optional_storage_path(name: str) -> Path | None:
    raw_value = _read_optional_str(name)
    if raw_value is None:
        return None

    return _resolve_storage_path(name, raw_value)


def _resolve_storage_path(name: str, default: str) -> Path:
    raw_value = os.getenv(name, default).strip() or default
    path = Path(raw_value)
    if path.is_absolute():
        return path

    project_path = PROJECT_ROOT / path
    package_path = PACKAGE_ROOT / path
    if project_path.exists() or not package_path.exists():
        return project_path

    return package_path


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    guild_id: int | None = None
    command_prefix: str = "!"
    environment: Literal["development", "production"] = "development"
    sync_scope: Literal["guild", "global"] = "guild"
    default_locale: str = "es-ES"
    locales_dir: Path = Path("aa_resources/locales")
    log_level: str = "INFO"
    log_dir: Path = Path("aa_var/logs")
    log_max_bytes: int = 1_048_576
    log_backup_count: int = 5
    log_all_messages: bool = False
    channel_access_range_start_role_id: int = 1_364_338_457_106_845_717
    channel_access_range_end_role_id: int = 1_364_336_738_323_009_796
    participant_role_id: int = 1_409_540_956_809_859_112
    player_role_id: int = 1_376_297_465_220_825_108
    gold_division_category_id: int = 1_487_858_997_812_789_298
    silver_division_category_id: int = 1_487_859_192_256_790_630
    timezone: str = "local"
    match_channel_ticket_url: str = "https://canary.discord.com/channels/1016819103555657851/1016824990949179512"
    match_channel_rules_url: str = "https://canary.discord.com/channels/1016819103555657851/1363537934665515351"
    google_service_account_file: Path | None = None
    google_sheets_spreadsheet_id: str = ""
    google_sheets_team_sheet_name: str = ""
    team_profile_font_path: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("Falta la variable de entorno DISCORD_TOKEN.")

        guild_id_raw = os.getenv("DISCORD_GUILD_ID", "").strip()
        guild_id = None

        if guild_id_raw:
            try:
                guild_id = int(guild_id_raw)
            except ValueError as exc:
                raise ValueError("DISCORD_GUILD_ID debe ser un entero valido.") from exc

        command_prefix = _read_str("BOT_PREFIX", "!")
        environment_raw = _read_str("BOT_ENV", "development").lower()
        if environment_raw not in {"development", "production"}:
            raise ValueError("BOT_ENV debe ser `development` o `production`.")

        default_sync_scope = "guild" if environment_raw == "development" else "global"
        sync_scope_raw = _read_str("BOT_SYNC_SCOPE", default_sync_scope).lower()
        if sync_scope_raw not in {"guild", "global"}:
            raise ValueError("BOT_SYNC_SCOPE debe ser `guild` o `global`.")

        if sync_scope_raw == "guild" and guild_id is None:
            raise ValueError(
                "BOT_SYNC_SCOPE=guild requiere que DISCORD_GUILD_ID este configurado."
            )

        default_locale = _read_str("BOT_DEFAULT_LOCALE", "es-ES")
        locales_dir = _resolve_storage_path("BOT_LOCALES_DIR", "aa_resources/locales")
        log_level = _read_str("BOT_LOG_LEVEL", "INFO").upper()
        log_dir = _resolve_storage_path("BOT_LOG_DIR", "aa_var/logs")
        log_max_bytes = _read_int("BOT_LOG_MAX_BYTES", 1_048_576)
        log_backup_count = _read_int("BOT_LOG_BACKUP_COUNT", 5)
        log_all_messages = _read_bool("BOT_LOG_ALL_MESSAGES", False)
        channel_access_range_start_role_id = _read_int(
            "BOT_CHANNEL_ACCESS_RANGE_START_ROLE_ID",
            1_364_338_457_106_845_717,
        )
        channel_access_range_end_role_id = _read_int(
            "BOT_CHANNEL_ACCESS_RANGE_END_ROLE_ID",
            1_364_336_738_323_009_796,
        )
        participant_role_id = _read_int(
            "BOT_PARTICIPANT_ROLE_ID",
            1_409_540_956_809_859_112,
        )
        player_role_id = _read_int(
            "BOT_PLAYER_ROLE_ID",
            1_376_297_465_220_825_108,
        )
        gold_division_category_id = _read_int(
            "BOT_GOLD_DIVISION_CATEGORY_ID",
            1_487_858_997_812_789_298,
        )
        silver_division_category_id = _read_int(
            "BOT_SILVER_DIVISION_CATEGORY_ID",
            1_487_859_192_256_790_630,
        )
        timezone = _read_str("BOT_TIMEZONE", "local")
        try:
            resolve_timezone(timezone)
        except ValueError as exc:
            raise ValueError(
                "BOT_TIMEZONE debe ser `local`, un offset como `+02:00`, o una zona IANA valida."
            ) from exc
        match_channel_ticket_url = _read_str(
            "BOT_MATCH_CHANNEL_TICKET_URL",
            "https://canary.discord.com/channels/1016819103555657851/1016824990949179512",
        )
        match_channel_rules_url = _read_str(
            "BOT_MATCH_CHANNEL_RULES_URL",
            "https://canary.discord.com/channels/1016819103555657851/1363537934665515351",
        )
        google_service_account_file = _resolve_optional_storage_path(
            "BOT_GOOGLE_SERVICE_ACCOUNT_FILE"
        )
        google_sheets_spreadsheet_id = _read_str(
            "BOT_GOOGLE_SHEETS_SPREADSHEET_ID",
            "",
        )
        google_sheets_team_sheet_name = _read_str(
            "BOT_GOOGLE_SHEETS_TEAM_SHEET_NAME",
            "",
        )
        team_profile_font_path = _resolve_optional_storage_path(
            "BOT_TEAM_PROFILE_FONT_PATH"
        )

        return cls(
            token=token,
            guild_id=guild_id,
            command_prefix=command_prefix,
            environment=environment_raw,
            sync_scope=sync_scope_raw,
            default_locale=default_locale,
            locales_dir=locales_dir,
            log_level=log_level,
            log_dir=log_dir,
            log_max_bytes=log_max_bytes,
            log_backup_count=log_backup_count,
            log_all_messages=log_all_messages,
            channel_access_range_start_role_id=channel_access_range_start_role_id,
            channel_access_range_end_role_id=channel_access_range_end_role_id,
            participant_role_id=participant_role_id,
            player_role_id=player_role_id,
            gold_division_category_id=gold_division_category_id,
            silver_division_category_id=silver_division_category_id,
            timezone=timezone,
            match_channel_ticket_url=match_channel_ticket_url,
            match_channel_rules_url=match_channel_rules_url,
            google_service_account_file=google_service_account_file,
            google_sheets_spreadsheet_id=google_sheets_spreadsheet_id,
            google_sheets_team_sheet_name=google_sheets_team_sheet_name,
            team_profile_font_path=team_profile_font_path,
        )
