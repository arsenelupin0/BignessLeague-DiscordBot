from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

DISCORD_MESSAGE_LINK_PATTERN = re.compile(
    r"^https?://(?:[\w-]+\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild_id>\d+)/(?P<channel_id>\d+)/(?P<message_id>\d+)/?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DiscordMessageReference:
    guild_id: int
    channel_id: int
    message_id: int


def parse_discord_message_reference(raw_link: str) -> DiscordMessageReference:
    match = DISCORD_MESSAGE_LINK_PATTERN.match(raw_link.strip())
    if match is None:
        raise CommandUserError(localize(I18N.errors.team_signing.invalid_message_link))

    return DiscordMessageReference(
        guild_id=int(match.group("guild_id")),
        channel_id=int(match.group("channel_id")),
        message_id=int(match.group("message_id")),
    )


async def fetch_linked_message(
        client: BignessLeagueBot,
        guild: discord.Guild,
        raw_link: str,
) -> discord.Message:
    message_reference = parse_discord_message_reference(raw_link)
    if message_reference.guild_id != guild.id:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.foreign_guild_message_link,
                expected_guild_id=str(guild.id),
                linked_guild_id=str(message_reference.guild_id),
            )
        )

    channel = guild.get_channel_or_thread(message_reference.channel_id)
    if channel is None:
        try:
            fetched_channel = await client.fetch_channel(message_reference.channel_id)
        except discord.NotFound as exc:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.message_channel_not_found,
                    channel_id=str(message_reference.channel_id),
                )
            ) from exc
        except discord.Forbidden as exc:
            raise CommandUserError(localize(I18N.errors.team_signing.message_fetch_forbidden)) from exc
        except discord.HTTPException as exc:
            raise CommandUserError(
                localize(
                    I18N.errors.team_signing.message_fetch_failed,
                    details=str(exc),
                )
            ) from exc

        if not isinstance(fetched_channel, (discord.TextChannel, discord.Thread)):
            raise CommandUserError(localize(I18N.errors.team_signing.unsupported_message_channel))

        channel = fetched_channel

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        raise CommandUserError(localize(I18N.errors.team_signing.unsupported_message_channel))

    try:
        return await channel.fetch_message(message_reference.message_id)
    except discord.NotFound as exc:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.message_not_found,
                message_id=str(message_reference.message_id),
            )
        ) from exc
    except discord.Forbidden as exc:
        raise CommandUserError(localize(I18N.errors.team_signing.message_fetch_forbidden)) from exc
    except discord.HTTPException as exc:
        raise CommandUserError(
            localize(
                I18N.errors.team_signing.message_fetch_failed,
                details=str(exc),
            )
        ) from exc
