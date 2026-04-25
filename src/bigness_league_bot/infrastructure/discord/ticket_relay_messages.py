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

from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.i18n.service import LocalizationService

MAX_RELAY_MESSAGE_LENGTH = 1_900
STAFF_DM_RELAY_COLOR = 0xF1C40F
PARTICIPANT_DM_RELAY_COLOR = 0x57F287


def truncate_relay_text(value: str) -> str:
    if len(value) <= MAX_RELAY_MESSAGE_LENGTH:
        return value

    return f"{value[:MAX_RELAY_MESSAGE_LENGTH]}...<truncated>"


def build_ticket_user_relay_message(
        *,
        localizer: LocalizationService,
        message: discord.Message,
) -> str:
    return truncate_relay_text(
        localizer.translate(
            I18N.messages.tickets.relay.from_user,
            author=message.author.mention,
            body=message_body(localizer=localizer, message=message),
        )
    )


def build_ticket_command_relay_message(
        *,
        localizer: LocalizationService,
        message: discord.Message,
        command_name: str,
) -> str:
    command_label = (
        command_name
        if command_name.startswith(("/", "!"))
        else f"/{command_name}"
    )
    return truncate_relay_text(
        localizer.translate(
            I18N.messages.tickets.relay.from_command_result,
            command_name=command_label,
            body=message_body(
                localizer=localizer,
                message=message,
                attachment_mode="names",
            ),
        )
    )


def build_ticket_dm_relay_embed(
        *,
        localizer: LocalizationService,
        message: discord.Message,
        color: int,
        is_staff: bool,
        mention_line: str,
        avatar_url: str | object,
) -> discord.Embed:
    body = message.content.strip()
    body_value = (
        truncate_relay_text(body)
        if body
        else localizer.translate(I18N.messages.tickets.relay.empty_body)
    )
    description = f"{mention_line}**:** {body_value}\n\n_ _"
    embed = discord.Embed(
        description=description,
        color=color,
        timestamp=message.created_at,
    )
    embed.set_author(
        name=localizer.translate(
            I18N.messages.tickets.relay.dm_staff_author
            if is_staff
            else I18N.messages.tickets.relay.dm_user_author
        ),
        icon_url=avatar_url,
    )
    embed.set_footer(
        text=localizer.translate(I18N.messages.tickets.open.embed.footer)
    )
    return embed


def message_body(
        *,
        localizer: LocalizationService,
        message: discord.Message,
        attachment_mode: str = "urls",
) -> str:
    content = message.content.strip()
    attachment_lines: list[str] = []
    if attachment_mode == "urls":
        attachment_lines = [
            f"- {attachment.url}"
            for attachment in message.attachments
        ]
    elif attachment_mode == "names":
        attachment_lines = [
            f"- {attachment.filename}"
            for attachment in message.attachments
        ]
    if attachment_lines:
        attachments = localizer.translate(
            I18N.messages.tickets.relay.attachments,
            urls="\n".join(attachment_lines),
        )
        content = f"{content}\n\n{attachments}" if content else attachments

    return content or localizer.translate(I18N.messages.tickets.relay.empty_body)


def relay_author_name(message: discord.Message) -> str:
    if message.guild is not None:
        member = message.guild.get_member(message.author.id)
        if member is not None:
            return member.display_name

    display_name = getattr(message.author, "display_name", None)
    if isinstance(display_name, str) and display_name.strip():
        return display_name

    global_name = getattr(message.author, "global_name", None)
    if isinstance(global_name, str) and global_name.strip():
        return global_name

    name = getattr(message.author, "name", None)
    if isinstance(name, str) and name.strip():
        return name

    return str(message.author)


def relay_visual_username(message: discord.Message) -> str:
    return f"@{relay_author_name(message)}"


def thread_relay_display_name(
        thread: discord.Thread,
        author: discord.abc.User | discord.User,
) -> str:
    member = thread.guild.get_member(author.id)
    if member is not None:
        return member.display_name

    global_name = getattr(author, "global_name", None)
    if isinstance(global_name, str) and global_name.strip():
        return global_name

    return author.name


def author_avatar_url(author: discord.abc.User | discord.User) -> str | object:
    avatar = getattr(author, "display_avatar", None)
    if avatar is None:
        return discord.utils.MISSING
    return avatar.url


def should_relay_bot_thread_message(message: discord.Message) -> bool:
    if not message_has_visible_payload(message):
        return False

    return message.interaction_metadata is not None


def looks_like_staff_relay_message(content: str) -> bool:
    prefix = I18N.messages.tickets.relay.from_staff.default.split("{author}")[0]
    return content.startswith(prefix)


def looks_like_user_relay_message(content: str) -> bool:
    prefix = I18N.messages.tickets.relay.from_user.default.split("{author}")[0]
    return content.startswith(prefix)


def looks_like_bot_command_relay_message(content: str) -> bool:
    prefix = I18N.messages.tickets.relay.from_command_result.default.split("{command_name}")[0]
    return content.startswith(prefix)


def relay_embed_description_for_ai(message: discord.Message) -> str | None:
    if not message.embeds:
        return None
    description = message.embeds[0].description
    if description is None:
        return None
    normalized = description.strip()
    return normalized or None


def relay_embed_color_value(message: discord.Message) -> int | None:
    if not message.embeds:
        return None
    color = message.embeds[0].colour
    if color is None:
        return None
    return color.value


def is_staff_dm_relay_message(message: discord.Message) -> bool:
    return relay_embed_color_value(message) == STAFF_DM_RELAY_COLOR


def is_participant_dm_relay_message(message: discord.Message) -> bool:
    return relay_embed_color_value(message) == PARTICIPANT_DM_RELAY_COLOR


def attachment_signature(
        attachments: list[discord.Attachment],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            attachment.filename,
            attachment.size,
            attachment.content_type,
            attachment.width,
            attachment.height,
        )
        for attachment in attachments
    )


def clone_message_embeds(message: discord.Message) -> list[discord.Embed]:
    return [
        discord.Embed.from_dict(embed.to_dict())
        for embed in message.embeds
    ]


async def clone_message_attachments_as_files(
        message: discord.Message,
) -> list[discord.File]:
    return [
        await attachment.to_file()
        for attachment in message.attachments
    ]


def should_retry_discord_http_error(error: discord.HTTPException) -> bool:
    return (
            isinstance(error, discord.DiscordServerError)
            or getattr(error, "status", None) in {500, 502, 503, 504}
    )


def yes_no(value: bool) -> str:
    return "si" if value else "no"


def message_has_visible_payload(message: discord.Message) -> bool:
    return bool(
        message.content.strip()
        or message.embeds
        or message.attachments
        or message.components
    )
