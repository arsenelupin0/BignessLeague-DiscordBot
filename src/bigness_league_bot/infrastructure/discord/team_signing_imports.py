from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.team_signing import (
    TeamSigningBatch,
    TeamSigningParseError,
    TeamTechnicalStaffBatch,
    parse_team_signing_message,
    parse_team_technical_staff_message,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.team_signing import fetch_linked_message
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


async def parse_player_signing_batch(
        client: BignessLeagueBot,
        *,
        guild: discord.Guild,
        message_link: str | None,
        require_team_logo: bool = True,
        min_players: int = 3,
) -> TeamSigningBatch | None:
    if message_link is None:
        return None

    linked_message = await fetch_linked_message(
        client,
        guild,
        message_link,
    )
    try:
        return parse_team_signing_message(
            linked_message.content,
            require_team_logo=require_team_logo,
            min_players=min_players,
        )
    except TeamSigningParseError as exc:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.invalid_message_format,
                details=str(exc),
            )
        ) from exc


async def parse_technical_staff_batch(
        client: BignessLeagueBot,
        *,
        guild: discord.Guild,
        message_link: str | None,
) -> TeamTechnicalStaffBatch | None:
    if message_link is None:
        return None

    linked_message = await fetch_linked_message(
        client,
        guild,
        message_link,
    )
    try:
        return parse_team_technical_staff_message(linked_message.content)
    except TeamSigningParseError as exc:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.invalid_technical_staff_message_format,
                details=str(exc),
            )
        ) from exc


def resolve_team_signing_import_target(
        *,
        signing_batch: TeamSigningBatch | None,
        technical_staff_batch: TeamTechnicalStaffBatch | None,
) -> tuple[str, str]:
    primary_batch = signing_batch or technical_staff_batch
    if primary_batch is None:
        raise CommandUserError(
            localize(I18N.errors.team_signing.no_import_payload_provided)
        )

    division_name = primary_batch.division_name
    team_name = primary_batch.team_name
    if (
            signing_batch is not None
            and technical_staff_batch is not None
            and (
            signing_batch.division_name != technical_staff_batch.division_name
            or signing_batch.team_name != technical_staff_batch.team_name
    )
    ):
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.import_payload_mismatch,
                player_division=signing_batch.division_name,
                player_team=signing_batch.team_name,
                staff_division=technical_staff_batch.division_name,
                staff_team=technical_staff_batch.team_name,
            )
        )

    return division_name, team_name
