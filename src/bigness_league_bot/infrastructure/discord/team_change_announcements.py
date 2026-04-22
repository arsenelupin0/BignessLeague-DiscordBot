from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.infrastructure.discord.team_role_removal_card import (
    build_team_role_removal_image_file,
)
from bigness_league_bot.infrastructure.google.team_sheet_repository import TeamRoleSheetMetadata
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

TEAM_CHANGE_FALLBACK_DIVISION_NAME = "Division no disponible"
TEAM_CHANGE_REMOVAL_EMBED_COLOR = 15_403_534
TEAM_CHANGE_SIGNING_EMBED_COLOR = 5_166_352
TEAM_CHANGE_STAFF_EMBED_COLOR = 14_606_862


@dataclass(frozen=True, slots=True)
class TeamChangeAnnouncementSpec:
    content_key: object
    action_key: object
    embed_color: int


TEAM_ROLE_REMOVAL_SPEC = TeamChangeAnnouncementSpec(
    content_key=I18N.messages.team_role_removal_announcement.content,
    action_key=I18N.messages.team_role_removal_announcement.action,
    embed_color=TEAM_CHANGE_REMOVAL_EMBED_COLOR,
)
TEAM_ROLE_SIGNING_SPEC = TeamChangeAnnouncementSpec(
    content_key=I18N.messages.team_role_signing_announcement.content,
    action_key=I18N.messages.team_role_signing_announcement.action,
    embed_color=TEAM_CHANGE_SIGNING_EMBED_COLOR,
)
TEAM_STAFF_ROLE_REMOVAL_SPEC = TeamChangeAnnouncementSpec(
    content_key=I18N.messages.team_staff_role_removal_announcement.content,
    action_key=I18N.messages.team_staff_role_removal_announcement.action,
    embed_color=TEAM_CHANGE_STAFF_EMBED_COLOR,
)
TEAM_STAFF_ROLE_SIGNING_SPEC = TeamChangeAnnouncementSpec(
    content_key=I18N.messages.team_staff_role_signing_announcement.content,
    action_key=I18N.messages.team_staff_role_signing_announcement.action,
    embed_color=TEAM_CHANGE_STAFF_EMBED_COLOR,
)


def build_team_change_content(
        *,
        bot: BignessLeagueBot,
        spec: TeamChangeAnnouncementSpec,
        member: discord.Member,
        team_role: discord.Role,
        guild: discord.Guild,
        staff_role_name: str | None = None,
) -> str:
    translation_kwargs = {
        "member_mention": member.mention,
        "team_role_mention": team_role.mention,
    }
    if staff_role_name is not None:
        translation_kwargs["staff_role_name"] = discord.utils.escape_markdown(
            staff_role_name
        )

    return bot.localizer.translate(
        spec.content_key,
        locale=bot.settings.default_locale,
        **translation_kwargs,
    )


def build_team_change_embed(
        *,
        bot: BignessLeagueBot,
        spec: TeamChangeAnnouncementSpec,
        member: discord.Member,
        team_role: discord.Role,
        guild: discord.Guild,
        metadata: TeamRoleSheetMetadata,
        description: str,
) -> tuple[discord.Embed, discord.File | None]:
    author_name = bot.localizer.translate(
        I18N.messages.team_role_removal_announcement.author,
        locale=bot.settings.default_locale,
        division_name=metadata.worksheet_title,
    )
    footer_text = bot.localizer.translate(
        I18N.messages.team_role_removal_announcement.footer,
        locale=bot.settings.default_locale,
    )
    action_text = bot.localizer.translate(
        spec.action_key,
        locale=bot.settings.default_locale,
    )

    embed = discord.Embed(
        description=description,
        color=spec.embed_color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(name=author_name)
    embed.set_footer(text=footer_text)

    thumbnail_url = metadata.team_image_url
    if not thumbnail_url and guild.icon is not None:
        thumbnail_url = guild.icon.url
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    try:
        image_file = build_team_role_removal_image_file(
            member=member,
            team_role=team_role,
            action_text=action_text,
            font_path=bot.settings.team_profile_font_path,
            accent_color=_embed_color_to_rgb(spec.embed_color),
        )
    except RuntimeError:
        embed.add_field(
            name="\u200b",
            value="\n".join(
                (
                    member.name,
                    "_ _",
                    f"**{action_text.upper()}**",
                    "_ _",
                    team_role.name,
                )
            ),
            inline=False,
        )
        return embed, None

    embed.set_image(url=f"attachment://{image_file.filename}")
    return embed, image_file


def build_team_role_sheet_metadata_fallback(team_role: discord.Role) -> TeamRoleSheetMetadata:
    return TeamRoleSheetMetadata(
        worksheet_title=TEAM_CHANGE_FALLBACK_DIVISION_NAME,
        team_name=team_role.name,
        team_image_url=None,
    )


def _embed_color_to_rgb(color: int) -> tuple[int, int, int]:
    return (
        (color >> 16) & 0xFF,
        (color >> 8) & 0xFF,
        color & 0xFF,
    )
