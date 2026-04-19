from __future__ import annotations

from dataclasses import dataclass

import discord
from discord.ext import commands


@dataclass(frozen=True, slots=True)
class DiscordEmojiRef:
    name: str
    id: int


TEAM_ROLE_REMOVAL_LEFT_ARROW_EMOJI = DiscordEmojiRef(
    name="flecha_derecha",
    id=1_495_240_882_868_322_385,
)
TEAM_ROLE_REMOVAL_INFO_ONE_EMOJI = DiscordEmojiRef(
    name="info_1",
    id=1_495_240_856_205_004_971,
)
TEAM_ROLE_REMOVAL_INFO_TWO_EMOJI = DiscordEmojiRef(
    name="info_2",
    id=1_495_240_818_255_204_372,
)
TEAM_ROLE_REMOVAL_RIGHT_ARROW_EMOJI = DiscordEmojiRef(
    name="flecha_izquierda",
    id=1_495_240_902_506_184_704,
)
TEAM_ROLE_REMOVAL_WARNING_EMOJI = DiscordEmojiRef(
    name="warning",
    id=1_495_252_797_862_707_250,
)


def render_custom_emoji(
        *,
        guild: discord.Guild,
        bot: commands.Bot,
        emoji: DiscordEmojiRef,
) -> str:
    resolved_emoji = guild.get_emoji(emoji.id) or bot.get_emoji(emoji.id)
    if resolved_emoji is not None:
        return str(resolved_emoji)

    return f"<:{emoji.name}:{emoji.id}>"
