from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bigness_league_bot.infrastructure.discord.team_signing_messages import (
    split_discord_message_content,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.ticket_command_mirroring import (
    mirror_ticket_text_command_message,
)

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

PUBLIC_HELP_SLASH_COMMAND_NAMES = (
    "horarios_fijados",
    "mmr_media",
    "ver_mi_equipo",
)


class TextCommandsCog(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @commands.command(name="help")
    async def help_command(
            self,
            ctx: commands.Context[BignessLeagueBot],
            section: str | None = None,
    ) -> None:
        content = _build_help_content(self.bot, section)
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="discordid")
    async def discord_id_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.discord_id_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="epicname")
    async def epic_name_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.epic_name_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="tracker")
    async def tracker_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.tracker_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="peak")
    async def peak_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.peak_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="idplataforma")
    async def platform_id_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.platform_id_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="equipo")
    async def team_info_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.team_info_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="datos")
    async def signing_data_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.signing_data_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="replays")
    async def replays_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.replays_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="info")
    async def league_info_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.league_info_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="infodis")
    async def discord_info_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.discord_info_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)

    @commands.command(name="faq")
    async def faq_help(
            self,
            ctx: commands.Context[BignessLeagueBot],
    ) -> None:
        content = self.bot.localizer.translate(
            I18N.messages.text_commands.faq_help.content,
        )
        await _send_text_command_content(self.bot, ctx, content)


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(TextCommandsCog(bot))


def _build_help_content(
        bot: BignessLeagueBot,
        section: str | None,
) -> str:
    normalized_section = (section or "").casefold()
    text_help = bot.localizer.translate(I18N.messages.text_commands.help.content)

    if normalized_section == "t":
        return text_help
    if normalized_section == "s":
        return _build_slash_command_help_content(bot)
    if normalized_section == "all":
        slash_help = _build_slash_command_help_content(
            bot,
            include_leading_separator=True,
        )
        return f"{text_help}{slash_help}"

    return bot.localizer.translate(I18N.messages.text_commands.help.usage)


def _build_slash_command_help_content(
        bot: BignessLeagueBot,
        *,
        include_leading_separator: bool = False,
) -> str:
    slash_command_lines = _build_slash_command_help_lines(bot)
    content = bot.localizer.translate(
        I18N.messages.text_commands.help.slash_section_title,
    )
    if not include_leading_separator:
        content = content.strip()
    if not slash_command_lines:
        content += "\n" + bot.localizer.translate(
            I18N.messages.text_commands.help.slash_empty,
        )
        return content

    return content + "\n" + "\n".join(slash_command_lines)


def _build_slash_command_help_lines(bot: BignessLeagueBot) -> list[str]:
    lines: list[str] = []
    commands_by_name = {
        command.name: command
        for command in bot.tree.get_commands()
    }
    for command_name in PUBLIC_HELP_SLASH_COMMAND_NAMES:
        command = commands_by_name.get(command_name)
        if command is None:
            continue
        lines.append(
            bot.localizer.translate(
                I18N.messages.text_commands.help.slash_command_line,
                name=command.name,
                description=command.description,
            )
        )

    return lines


async def _send_text_command_content(
        bot: BignessLeagueBot,
        ctx: commands.Context[BignessLeagueBot],
        content: str,
) -> None:
    for chunk in split_discord_message_content(content):
        sent_message = await ctx.send(
            chunk,
            allowed_mentions=discord.AllowedMentions.none(),
            suppress_embeds=True,
        )
        if ctx.command is not None:
            invoked_command_name = ctx.invoked_with or ctx.command.qualified_name
            await mirror_ticket_text_command_message(
                bot,
                sent_message,
                command_name=f"!{invoked_command_name}",
            )
