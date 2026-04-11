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

from dataclasses import dataclass
from typing import Literal

import discord
from discord import app_commands


@dataclass(frozen=True, slots=True)
class SyncReport:
    scope: str
    command_names: tuple[str, ...]
    guild_id: int | None = None

    @property
    def command_count(self) -> int:
        return len(self.command_names)

    def format_summary(self) -> str:
        scope_label = "global"
        if self.guild_id is not None:
            scope_label = f"guild:{self.guild_id}"

        commands_label = ", ".join(self.command_names) if self.command_names else "(sin comandos)"
        return (
            f"scope={scope_label} total={self.command_count} "
            f"commands=[{commands_label}]"
        )


def _local_command_name(
        command: app_commands.Command | app_commands.Group | app_commands.ContextMenu,
) -> str:
    return command.qualified_name


def _synced_command_name(command: app_commands.AppCommand) -> str:
    return command.name


def get_local_command_names(tree: app_commands.CommandTree) -> tuple[str, ...]:
    commands = tree.get_commands()
    return tuple(sorted(_local_command_name(command) for command in commands))


async def sync_command_tree(
        tree: app_commands.CommandTree,
        sync_scope: Literal["guild", "global"],
        guild_id: int | None,
) -> SyncReport:
    if sync_scope == "guild":
        if guild_id is None:
            raise ValueError("No se puede sincronizar por guild sin DISCORD_GUILD_ID.")

        guild = discord.Object(id=guild_id)
        tree.copy_global_to(guild=guild)
        synced_commands = await tree.sync(guild=guild)
        return SyncReport(
            scope="guild",
            guild_id=guild_id,
            command_names=tuple(_synced_command_name(command) for command in synced_commands),
        )

    synced_commands = await tree.sync()
    return SyncReport(
        scope="global",
        command_names=tuple(_synced_command_name(command) for command in synced_commands),
    )
