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

from discord.ext import commands

from bigness_league_bot.infrastructure.discord.sync import (
    get_local_command_names,
    prune_command_scope,
    sync_command_tree,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


class Admin(commands.Cog):
    def __init__(self, bot: BignessLeagueBot) -> None:
        self.bot = bot

    @commands.command(name="sync")
    @commands.is_owner()
    async def sync_commands(
            self,
            ctx: commands.Context[BignessLeagueBot],
            action: str | None = None,
            scope: str | None = None,
    ) -> None:
        normalized_action = (action or "").lower().strip()
        normalized_scope = (scope or "").lower().strip()

        if normalized_action == "prune":
            prune_scope = normalized_scope or "other"
            if prune_scope == "other":
                prune_scope = "global" if self.bot.settings.sync_scope == "guild" else "guild"

            if prune_scope not in {"guild", "global"}:
                await ctx.send(
                    self.bot.localizer.translate(I18N.messages.admin.sync.invalid_usage)
                )
                return

            try:
                report = await prune_command_scope(
                    self.bot.tree,
                    prune_scope,
                    self.bot.settings.guild_id,
                )
            except ValueError:
                await ctx.send(
                    self.bot.localizer.translate(
                        I18N.messages.admin.sync.guild_id_required
                    )
                )
                return

            await ctx.send(
                self.bot.localizer.translate(
                    I18N.messages.admin.sync.pruned,
                    summary=report.format_summary(),
                )
            )
            return

        normalized_scope = normalized_action or self.bot.settings.sync_scope
        normalized_scope = normalized_scope.lower().strip()
        if normalized_scope not in {"guild", "global"}:
            await ctx.send(
                self.bot.localizer.translate(I18N.messages.admin.sync.invalid_usage)
            )
            return

        if normalized_scope != self.bot.settings.sync_scope:
            await ctx.send(
                self.bot.localizer.translate(
                    I18N.messages.admin.sync.scope_locked,
                    sync_scope=self.bot.settings.sync_scope,
                )
            )
            return

        report = await sync_command_tree(
            self.bot.tree,
            self.bot.settings.sync_scope,
            self.bot.settings.guild_id,
        )
        await ctx.send(
            self.bot.localizer.translate(
                I18N.messages.admin.sync.completed,
                summary=report.format_summary(),
            )
        )

    @commands.command(name="slashstatus")
    @commands.is_owner()
    async def slash_status(self, ctx: commands.Context[BignessLeagueBot]) -> None:
        local_commands = get_local_command_names(self.bot.tree)
        commands_label = ", ".join(local_commands) if local_commands else "(ninguno)"
        await ctx.send(
            self.bot.localizer.translate(
                I18N.messages.admin.slash_status.result,
                guild_id=self.bot.settings.guild_id or "(sin configurar)",
                commands=commands_label,
            )
        )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(Admin(bot))
