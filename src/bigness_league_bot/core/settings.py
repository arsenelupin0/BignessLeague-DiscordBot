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

        command_prefix = os.getenv("BOT_PREFIX", "!").strip() or "!"
        environment_raw = os.getenv("BOT_ENV", "development").strip().lower() or "development"
        if environment_raw not in {"development", "production"}:
            raise ValueError("BOT_ENV debe ser `development` o `production`.")

        default_sync_scope = "guild" if environment_raw == "development" else "global"
        sync_scope_raw = os.getenv("BOT_SYNC_SCOPE", default_sync_scope).strip().lower() or default_sync_scope
        if sync_scope_raw not in {"guild", "global"}:
            raise ValueError("BOT_SYNC_SCOPE debe ser `guild` o `global`.")

        if sync_scope_raw == "guild" and guild_id is None:
            raise ValueError(
                "BOT_SYNC_SCOPE=guild requiere que DISCORD_GUILD_ID este configurado."
            )

        default_locale = os.getenv("BOT_DEFAULT_LOCALE", "es-ES").strip() or "es-ES"
        locales_dir = _resolve_storage_path("BOT_LOCALES_DIR", "aa_resources/locales")
        log_level = os.getenv("BOT_LOG_LEVEL", "INFO").strip().upper() or "INFO"
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
        )
