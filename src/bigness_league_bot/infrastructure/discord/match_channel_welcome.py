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

from dataclasses import dataclass

import discord

from bigness_league_bot.application.services.channel_closure import format_match_channel_number
from bigness_league_bot.application.services.match_channel_creation import MatchChannelSpecification
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

DETAILS_EMBED_COLOR = 3_073_295
MATCH_DATA_EMBED_COLOR = 15_013_141


@dataclass(frozen=True, slots=True)
class MatchChannelWelcomeMessage:
    content: str
    embeds: tuple[discord.Embed, ...]
    view: discord.ui.View


def _welcome_template_params(
        specification: MatchChannelSpecification,
        team_one: discord.Role,
        team_two: discord.Role,
) -> dict[str, str]:
    return {
        "jornada_emoji": format_match_channel_number(specification.jornada),
        "partido_emoji": format_match_channel_number(specification.partido),
        "team_one": team_one.mention,
        "team_two": team_two.mention,
        "courtesy_minutes": str(specification.courtesy_minutes),
        "match_date": f"<t:{specification.start_timestamp}:D>",
        "match_time": f"<t:{specification.start_timestamp}:t>",
        "best_of": str(specification.best_of),
        "best_of_label": f"Bo{specification.best_of}",
        "room_name": specification.room_name,
        "room_password": specification.room_password,
    }


def _build_button_view(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        settings: Settings,
) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label=localizer.translate(
                I18N.messages.match_channel_creation.welcome.buttons.create_ticket,
                locale=locale,
            ),
            style=discord.ButtonStyle.link,
            url=settings.match_channel_ticket_url,
            emoji="\U0001f3ab",
        )
    )
    view.add_item(
        discord.ui.Button(
            label=localizer.translate(
                I18N.messages.match_channel_creation.welcome.buttons.rules,
                locale=locale,
            ),
            style=discord.ButtonStyle.link,
            url=settings.match_channel_rules_url,
            emoji="\U0001f4dc",
        )
    )
    return view


def build_match_channel_welcome_message(
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        settings: Settings,
        specification: MatchChannelSpecification,
        team_one: discord.Role,
        team_two: discord.Role,
) -> MatchChannelWelcomeMessage:
    params = _welcome_template_params(specification, team_one, team_two)
    details_embed = discord.Embed(
        title=localizer.translate(
            I18N.messages.match_channel_creation.welcome.embeds.details.title,
            locale=locale,
        ),
        description=localizer.translate(
            I18N.messages.match_channel_creation.welcome.embeds.details.description,
            locale=locale,
            **params,
        ),
        color=DETAILS_EMBED_COLOR,
    )
    issues_embed = discord.Embed(
        title=localizer.translate(
            I18N.messages.match_channel_creation.welcome.embeds.issues.title,
            locale=locale,
        ),
        description=localizer.translate(
            I18N.messages.match_channel_creation.welcome.embeds.issues.description,
            locale=locale,
            **params,
        ),
        color=DETAILS_EMBED_COLOR,
    )
    match_data_embed = discord.Embed(
        title=localizer.translate(
            I18N.messages.match_channel_creation.welcome.embeds.match_data.title,
            locale=locale,
        ),
        description=localizer.translate(
            I18N.messages.match_channel_creation.welcome.embeds.match_data.description,
            locale=locale,
            **params,
        ),
        color=MATCH_DATA_EMBED_COLOR,
    )
    return MatchChannelWelcomeMessage(
        content=localizer.translate(
            I18N.messages.match_channel_creation.welcome.content,
            locale=locale,
            **params,
        ),
        embeds=(details_embed, issues_embed, match_data_embed),
        view=_build_button_view(
            localizer=localizer,
            locale=locale,
            settings=settings,
        ),
    )


async def send_match_channel_welcome_message(
        *,
        channel: discord.TextChannel,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
        settings: Settings,
        specification: MatchChannelSpecification,
        team_one: discord.Role,
        team_two: discord.Role,
) -> discord.Message:
    welcome_message = build_match_channel_welcome_message(
        localizer=localizer,
        locale=locale,
        settings=settings,
        specification=specification,
        team_one=team_one,
        team_two=team_two,
    )
    return await channel.send(
        content=welcome_message.content,
        embeds=list(welcome_message.embeds),
        view=welcome_message.view,
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=False,
            everyone=False,
            replied_user=False,
        ),
    )
