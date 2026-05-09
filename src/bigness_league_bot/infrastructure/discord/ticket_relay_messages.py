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

from collections.abc import Sequence
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


def build_ticket_deleted_user_relay_message(
        *,
        localizer: LocalizationService,
        message: discord.Message,
) -> str:
    return truncate_relay_text(
        localizer.translate(
            I18N.messages.tickets.relay.from_user,
            author=message.author.mention,
            body=deleted_message_body(localizer=localizer, message=message),
        )
    )


def build_ticket_command_relay_message(
        *,
        localizer: LocalizationService,
        message: discord.Message,
        command_name: str,
        body_override: str | None = None,
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
            body=(
                    body_override
                    or message_body(
                localizer=localizer,
                message=message,
                attachment_mode="names",
            )
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
        avatar_url: str,
        deleted: bool = False,
) -> discord.Embed:
    body_value = (
        deleted_message_body(localizer=localizer, message=message)
        if deleted
        else message_content_body(localizer=localizer, message=message)
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


def deleted_message_body(
        *,
        localizer: LocalizationService,
        message: discord.Message,
        attachment_mode: str = "urls",
) -> str:
    return localizer.translate(
        I18N.messages.tickets.relay.deleted_body,
        body=message_body(
            localizer=localizer,
            message=message,
            attachment_mode=attachment_mode,
        ),
    )


def message_body(
        *,
        localizer: LocalizationService,
        message: discord.Message,
        attachment_mode: str = "urls",
) -> str:
    content = _visible_message_body(
        localizer=localizer,
        message=message,
        attachment_mode=attachment_mode,
        include_direct_attachments=True,
    )

    return content or localizer.translate(I18N.messages.tickets.relay.empty_body)


def message_content_body(
        *,
        localizer: LocalizationService,
        message: discord.Message,
) -> str:
    body = _visible_message_body(
        localizer=localizer,
        message=message,
        attachment_mode="urls",
        include_direct_attachments=False,
    )
    return (
        truncate_relay_text(body)
        if body
        else localizer.translate(I18N.messages.tickets.relay.empty_body)
    )


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

    return _fallback_author_name(message.author)


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


def author_avatar_url(author: discord.abc.User | discord.User) -> str:
    avatar = author.display_avatar
    if avatar is None:
        return ""

    return avatar.url


def _fallback_author_name(author: discord.abc.User | discord.User) -> str:
    if isinstance(author.name, str) and author.name.strip():
        return author.name

    return f"user-{author.id}"


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
        or _stickers_from(message)
        or _message_snapshots(message)
    )


def _visible_message_body(
        *,
        localizer: LocalizationService,
        message: discord.Message,
        attachment_mode: str,
        include_direct_attachments: bool,
) -> str:
    parts: list[str] = []
    content = message.content.strip()
    if content:
        parts.append(content)

    for snapshot in _message_snapshots(message):
        snapshot_body = _snapshot_body(
            localizer=localizer,
            snapshot=snapshot,
            attachment_mode=attachment_mode,
        )
        if not snapshot_body:
            continue
        parts.append(
            localizer.translate(
                I18N.messages.tickets.relay.forwarded_body,
                body=snapshot_body,
            )
        )

    if include_direct_attachments:
        attachments = _attachments_body(
            localizer=localizer,
            attachments=message.attachments,
            attachment_mode=attachment_mode,
        )
        if attachments:
            parts.append(attachments)

    stickers = _stickers_body(
        localizer=localizer,
        stickers=_stickers_from(message),
        attachment_mode=attachment_mode,
    )
    if stickers:
        parts.append(stickers)

    return "\n\n".join(parts).strip()


def _snapshot_body(
        *,
        localizer: LocalizationService,
        snapshot: object,
        attachment_mode: str,
) -> str:
    parts: list[str] = []
    content = getattr(snapshot, "content", None)
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())

    embed_body = _snapshot_embed_body(snapshot)
    if embed_body:
        parts.append(embed_body)

    attachments = _object_sequence(getattr(snapshot, "attachments", None))
    if attachments:
        attachments_body = _attachments_body(
            localizer=localizer,
            attachments=attachments,
            attachment_mode=attachment_mode,
        )
        if attachments_body:
            parts.append(attachments_body)

    stickers_body = _stickers_body(
        localizer=localizer,
        stickers=_stickers_from(snapshot),
        attachment_mode=attachment_mode,
    )
    if stickers_body:
        parts.append(stickers_body)

    return "\n\n".join(parts).strip()


def _snapshot_embed_body(snapshot: object) -> str | None:
    embeds = getattr(snapshot, "embeds", None)
    if not isinstance(embeds, list):
        return None

    lines: list[str] = []
    for embed in embeds:
        title = getattr(embed, "title", None)
        if isinstance(title, str) and title.strip():
            lines.append(title.strip())
        description = getattr(embed, "description", None)
        if isinstance(description, str) and description.strip():
            lines.append(description.strip())

    return "\n".join(lines).strip() or None


def _attachments_body(
        *,
        localizer: LocalizationService,
        attachments: Sequence[object],
        attachment_mode: str,
) -> str | None:
    attachment_lines = _attachment_lines(
        attachments=attachments,
        attachment_mode=attachment_mode,
    )
    if not attachment_lines:
        return None

    return localizer.translate(
        I18N.messages.tickets.relay.attachments,
        urls="\n".join(attachment_lines),
    )


def _stickers_body(
        *,
        localizer: LocalizationService,
        stickers: tuple[object, ...],
        attachment_mode: str,
) -> str | None:
    sticker_lines = _sticker_lines(stickers=stickers, attachment_mode=attachment_mode)
    if not sticker_lines:
        return None

    return localizer.translate(
        I18N.messages.tickets.relay.stickers,
        stickers="\n".join(sticker_lines),
    )


def _sticker_lines(
        *,
        stickers: tuple[object, ...],
        attachment_mode: str,
) -> list[str]:
    lines: list[str] = []
    for sticker in stickers:
        name = _sticker_name(sticker)
        if attachment_mode == "names":
            lines.append(f"- {name}")
            continue
        preview_url = _sticker_preview_url(sticker)
        source_url = _sticker_source_url(sticker)
        if preview_url is not None and preview_url != source_url:
            lines.append(str(preview_url))
        lines.append(f"- {name}: {source_url}" if source_url else f"- {name}")
    return lines


def _sticker_name(sticker: object) -> str:
    name = getattr(sticker, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()

    sticker_id = getattr(sticker, "id", None)
    if isinstance(sticker_id, int):
        return f"sticker-{sticker_id}"

    return "sticker"


def _sticker_source_url(sticker: object) -> str | None:
    url = getattr(sticker, "url", None)
    if isinstance(url, str) and url.strip():
        return url.strip()
    if url is not None:
        resolved_url = str(url).strip()
        if resolved_url:
            return resolved_url

    sticker_id = _sticker_id(sticker)
    if sticker_id is not None:
        return _sticker_preview_url_from_id(sticker_id)

    return None


def _sticker_preview_url(sticker: object) -> str | None:
    source_url = _sticker_source_url(sticker)
    if source_url is not None:
        return source_url if _is_renderable_sticker_url(source_url) else None

    sticker_id = _sticker_id(sticker)
    if sticker_id is None:
        return None
    return _sticker_preview_url_from_id(sticker_id)


def _sticker_preview_url_from_id(sticker_id: int) -> str:
    return f"https://media.discordapp.net/stickers/{sticker_id}.png"


def _sticker_id(sticker: object) -> int | None:
    sticker_id = getattr(sticker, "id", None)
    if isinstance(sticker_id, int):
        return sticker_id
    if isinstance(sticker_id, str) and sticker_id.isdigit():
        return int(sticker_id)
    return None


def _is_renderable_sticker_url(url: str) -> bool:
    normalized_url = url.casefold().split("?", maxsplit=1)[0]
    return normalized_url.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


def _stickers_from(source: object) -> tuple[object, ...]:
    return (
            _object_sequence(getattr(source, "stickers", None))
            or _object_sequence(getattr(source, "sticker_items", None))
    )


def _attachment_lines(
        *,
        attachments: Sequence[object],
        attachment_mode: str,
) -> list[str]:
    if attachment_mode == "urls":
        return [
            f"- {_attachment_url(attachment)}"
            for attachment in attachments
            if _attachment_url(attachment)
        ]
    if attachment_mode == "names":
        return [
            f"- {_attachment_filename(attachment)}"
            for attachment in attachments
            if _attachment_filename(attachment)
        ]
    return []


def _attachment_url(attachment: object) -> str | None:
    url = getattr(attachment, "url", None)
    if isinstance(url, str) and url.strip():
        return url.strip()
    if url is not None:
        resolved_url = str(url).strip()
        if resolved_url:
            return resolved_url
    return None


def _attachment_filename(attachment: object) -> str | None:
    filename = getattr(attachment, "filename", None)
    if isinstance(filename, str) and filename.strip():
        return filename.strip()
    return None


def _message_snapshots(message: discord.Message) -> tuple[object, ...]:
    return _object_sequence(getattr(message, "message_snapshots", None))


def _object_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()
