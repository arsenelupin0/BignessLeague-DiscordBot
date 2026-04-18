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

from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import (
    format_ticket_created_at,
    format_ticket_duration,
    format_ticket_number,
    parse_utc_timestamp,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

TICKET_OPEN_COLOR = 16_711_680
TICKET_CLOSED_COLOR = 3_447_003
SUCCESS_EMOJI_NAME = "correctButton"


def build_ticket_message_content(user: discord.abc.User | discord.Member) -> str:
    return user.mention


def build_ticket_open_message_content() -> None:
    return None


def build_ticket_opening_notice(user: discord.abc.User | discord.Member) -> str:
    return (
        f"\n\n_ _\nHola {user.mention}, ¡tu ticket ha sido abierto! "
        "Explica con brevedad que es lo que necesitas. "
        "Alguien del **Staff** te atenderá lo antes posible."
    )


def build_ticket_open_embed(
        *,
        bot: BignessLeagueBot,
        locale: str | discord.Locale | None,
        guild: discord.Guild | None,
        opened_by: discord.abc.User | discord.Member,
        category_label: str,
        ticket_number: int,
        created_at: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=bot.localizer.translate(
            I18N.messages.tickets.open.embed.title,
            locale=locale,
        ),
        description=bot.localizer.translate(
            I18N.messages.tickets.open.embed.description,
            locale=locale,
        ),
        color=TICKET_OPEN_COLOR,
        timestamp=parse_utc_timestamp(created_at),
    )
    embed.set_author(
        name=guild.name if guild is not None else "Bigness League",
        icon_url=resolve_embed_icon_url(bot, guild),
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.open.embed.fields.ticket_number,
            locale=locale,
        ),
        value=with_visual_spacing(f"``{format_ticket_number(ticket_number)}``"),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.open.embed.fields.opened_by,
            locale=locale,
        ),
        value=with_visual_spacing(opened_by.mention),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.open.embed.fields.category,
            locale=locale,
        ),
        value=with_visual_spacing(category_label),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.open.embed.fields.created_at,
            locale=locale,
        ),
        value=with_visual_spacing(format_ticket_created_at(created_at)),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.open.embed.fields.instructions,
            locale=locale,
        ),
        value=with_visual_spacing(
            bot.localizer.translate(
                I18N.messages.tickets.open.embed.instructions,
                locale=locale,
            )
        ),
        inline=False,
    )
    embed.set_footer(
        text=bot.localizer.translate(
            I18N.messages.tickets.open.embed.footer,
            locale=locale,
        )
    )
    return embed


def build_ticket_close_embed(
        *,
        bot: BignessLeagueBot,
        locale: str | discord.Locale | None,
        guild: discord.Guild | None,
        closed_by: discord.abc.User | discord.Member,
        category_label: str,
        ticket_number: int,
        ticket_link: str | None,
        created_at: str,
        closed_at: str,
        close_reason: str | None,
) -> discord.Embed:
    embed = discord.Embed(
        title=bot.localizer.translate(
            I18N.messages.tickets.close.embed.title,
            locale=locale,
        ),
        description=bot.localizer.translate(
            I18N.messages.tickets.close.embed.description,
            locale=locale,
        ),
        color=TICKET_CLOSED_COLOR,
        timestamp=parse_utc_timestamp(closed_at),
    )
    embed.set_author(
        name=guild.name if guild is not None else "Bigness League",
        icon_url=resolve_embed_icon_url(bot, guild),
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.ticket_number,
            locale=locale,
        ),
        value=with_visual_spacing(f"``{format_ticket_number(ticket_number)}``"),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.closed_by,
            locale=locale,
        ),
        value=with_visual_spacing(closed_by.mention),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.category,
            locale=locale,
        ),
        value=with_visual_spacing(category_label),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.ticket_link,
            locale=locale,
        ),
        value=with_visual_spacing(
            (
                bot.localizer.translate(
                    I18N.messages.tickets.close.embed.link_value,
                    locale=locale,
                    ticket_link=ticket_link,
                )
                if ticket_link is not None
                else "-"
            )
        ),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.created_at,
            locale=locale,
        ),
        value=with_visual_spacing(format_ticket_created_at(created_at)),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.duration,
            locale=locale,
        ),
        value=with_visual_spacing(
            format_ticket_duration(
                created_at=created_at,
                closed_at=closed_at,
            )
        ),
        inline=False,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.closed_at,
            locale=locale,
        ),
        value=with_visual_spacing(format_ticket_created_at(closed_at)),
        inline=False,
    )
    reason_value = close_reason or bot.localizer.translate(
        I18N.messages.tickets.close.embed.default_reason,
        locale=locale,
    )
    embed.add_field(
        name=bot.localizer.translate(
            I18N.messages.tickets.close.embed.fields.close_reason,
            locale=locale,
        ),
        value=f"```\n{reason_value}\n```",
        inline=False,
    )
    embed.set_footer(
        text=bot.localizer.translate(
            I18N.messages.tickets.close.embed.footer,
            locale=locale,
        )
    )
    return embed


def resolve_embed_icon_url(
        bot: BignessLeagueBot,
        guild: discord.Guild | None,
) -> str | None:
    if guild is not None and guild.icon is not None:
        return guild.icon.url

    bot_user = bot.user
    if bot_user is not None:
        return bot_user.display_avatar.url

    return None


def with_visual_spacing(value: str) -> str:
    return f"{value}\n \n_ _"


def resolve_success_emoji(guild: discord.Guild | None) -> str:
    if guild is not None:
        for emoji in guild.emojis:
            if emoji.name == SUCCESS_EMOJI_NAME:
                return str(emoji)

    return "✅"
