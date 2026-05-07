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

from collections.abc import Iterable
from pathlib import Path

import discord

from bigness_league_bot.application.services.match_replay_summaries import MatchReplayTeamLogo


def team_logo_url_map(team_logos: Iterable[MatchReplayTeamLogo]) -> dict[str, str]:
    logo_urls: dict[str, str] = {}
    for team_logo in team_logos:
        if not team_logo.team_name.strip():
            continue
        if not isinstance(team_logo.logo_url, str) or not team_logo.logo_url.strip():
            continue
        logo_urls[_normalize_lookup_text(team_logo.team_name)] = team_logo.logo_url.strip()
    return logo_urls


def guild_icon_url(guild: discord.Guild | None) -> str | None:
    if guild is None:
        return None
    icon = guild.icon
    if icon is None:
        return None
    return str(icon.url)


def write_replay_diagnostic_copy(
        *,
        diagnostics_dir: Path,
        filename: str,
        content: bytes,
        digest: str,
) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_path = diagnostics_dir / f"{digest[:16]}-{safe_replay_filename(filename)}"
    if not diagnostics_path.exists():
        diagnostics_path.write_bytes(content)
    return diagnostics_path


def safe_replay_filename(filename: str) -> str:
    safe_characters = [
        character if character.isalnum() or character in {".", "-", "_"} else "_"
        for character in filename
    ]
    return "".join(safe_characters) or "replay.replay"


def _normalize_lookup_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())
