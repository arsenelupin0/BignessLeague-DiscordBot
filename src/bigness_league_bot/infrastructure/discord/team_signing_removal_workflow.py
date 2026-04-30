from __future__ import annotations

from time import monotonic
from typing import Literal, TYPE_CHECKING

import discord

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.discord.channel_access_management import (
    get_channel_access_role_catalog,
)
from bigness_league_bot.infrastructure.discord.team_role_assignment import (
    resolve_player_role,
)
from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    build_team_signing_removal_completed_message,
    build_team_signing_removal_visibility_message,
)
from bigness_league_bot.infrastructure.discord.team_signing_role_reconciliation import (
    remove_discord_roles_after_signing_removal,
)
from bigness_league_bot.infrastructure.discord.team_signing_visibility import (
    collect_team_signing_removal_visibility_links,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import (
    GoogleSheetsTeamRepository,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

TeamSigningRemovalScope = Literal["all", "player", "staff"]


async def handle_team_signing_removal(
        interaction: discord.Interaction[BignessLeagueBot],
        *,
        guild: discord.Guild,
        discord_name: str,
        team_role: discord.Role,
        removal_scope: TeamSigningRemovalScope,
) -> None:
    settings = interaction.client.settings
    role_catalog = get_channel_access_role_catalog(
        guild,
        settings.channel_access_range_start_role_id,
        settings.channel_access_range_end_role_id,
    )
    if team_role.id not in {role.id for role in role_catalog.roles}:
        raise CommandUserError(
            localize(
                I18N.errors.match_channel_creation.team_role_out_of_range,
                role_name=team_role.name,
                range_start=role_catalog.range_start.name,
                range_end=role_catalog.range_end.name,
            )
        )

    repository = GoogleSheetsTeamRepository(settings)
    if removal_scope == "player":
        result = await repository.remove_team_player_by_discord(
            discord_name,
            team_name=team_role.name,
        )
    elif removal_scope == "staff":
        result = await repository.remove_team_staff_by_discord(
            discord_name,
            team_name=team_role.name,
        )
    else:
        result = await repository.remove_team_member_by_discord(
            discord_name,
            team_name=team_role.name,
        )

    player_role = resolve_player_role(guild, settings.player_role_id)
    announcement_since = monotonic()
    role_removal_report = await remove_discord_roles_after_signing_removal(
        interaction,
        discord_name=discord_name,
        result=result,
    )
    visibility_links = await collect_team_signing_removal_visibility_links(
        settings=settings,
        guild=guild,
        team_role=team_role,
        player_role=player_role,
        result=result,
        removal_summary=role_removal_report.summary,
        since=announcement_since,
    )
    followup_message = build_team_signing_removal_completed_message(
        localizer=interaction.client.localizer,
        locale=interaction.locale,
        discord_name=discord_name,
        result=result,
    )
    if role_removal_report.message:
        followup_message = f"{followup_message}\n{role_removal_report.message}"

    visibility_message = build_team_signing_removal_visibility_message(
        localizer=interaction.client.localizer,
        locale=interaction.locale,
        team_role_mention=team_role.mention,
        team_links=visibility_links.team_links,
        player_links=visibility_links.player_links,
        staff_links=visibility_links.staff_links,
    )

    await interaction.followup.send(
        f"{followup_message}{visibility_message}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
