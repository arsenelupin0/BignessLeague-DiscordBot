#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands

from bigness_league_bot.infrastructure.discord.sync import (
    get_local_command_names,
    sync_command_tree,
)

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
            scope: str | None = None,
    ) -> None:
        normalized_scope = (scope or self.bot.settings.sync_scope).lower().strip()
        if normalized_scope not in {"guild", "global"}:
            await ctx.send("Usa `!sync guild` o `!sync global`.")
            return

        if normalized_scope != self.bot.settings.sync_scope:
            await ctx.send(
                "El bot esta configurado para "
                f"`BOT_SYNC_SCOPE={self.bot.settings.sync_scope}`. "
                "Cambia el `.env` y reinicia si quieres usar el otro scope."
            )
            return

        report = await sync_command_tree(
            self.bot.tree,
            self.bot.settings.sync_scope,
            self.bot.settings.guild_id,
        )
        await ctx.send(f"Sincronizacion completada: {report.format_summary()}")

    @commands.command(name="slashstatus")
    @commands.is_owner()
    async def slash_status(self, ctx: commands.Context[BignessLeagueBot]) -> None:
        local_commands = get_local_command_names(self.bot.tree)
        commands_label = ", ".join(local_commands) if local_commands else "(ninguno)"
        await ctx.send(
            "Estado local de slash commands: "
            f"guild_id={self.bot.settings.guild_id or '(sin configurar)'} "
            f"commands=[{commands_label}]"
        )


async def setup(bot: BignessLeagueBot) -> None:
    await bot.add_cog(Admin(bot))
