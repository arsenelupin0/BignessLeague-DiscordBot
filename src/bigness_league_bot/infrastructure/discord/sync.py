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


@dataclass(frozen=True, slots=True)
class PruneReport:
    scope: str
    deleted_command_names: tuple[str, ...]
    guild_id: int | None = None

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_command_names)

    def format_summary(self) -> str:
        scope_label = "global"
        if self.guild_id is not None:
            scope_label = f"guild:{self.guild_id}"

        commands_label = ", ".join(self.deleted_command_names) if self.deleted_command_names else "(sin comandos)"
        return (
            f"scope={scope_label} removed={self.deleted_count} "
            f"commands=[{commands_label}]"
        )


def _local_command_name(
        command: app_commands.Command | app_commands.Group | app_commands.ContextMenu,
) -> str:
    return command.qualified_name


def _synced_command_name(command: app_commands.AppCommand) -> str:
    return command.name


def _synced_http_command_name(command: object) -> str:
    if isinstance(command, app_commands.AppCommand):
        return command.name

    if isinstance(command, dict):
        name = command.get("name")
        if isinstance(name, str):
            return name

    raise TypeError(
        f"No se pudo resolver el nombre del comando sincronizado: {command!r}"
    )


def get_local_command_names(tree: app_commands.CommandTree) -> tuple[str, ...]:
    commands = tree.get_commands()
    return tuple(sorted(_local_command_name(command) for command in commands))


def _supports_dm_context(
        command: app_commands.Command | app_commands.Group | app_commands.ContextMenu,
) -> bool:
    allowed_contexts = getattr(command, "allowed_contexts", None)
    if allowed_contexts is None:
        return False

    return bool(allowed_contexts.dm_channel or allowed_contexts.private_channel)


def get_dm_command_names(tree: app_commands.CommandTree) -> tuple[str, ...]:
    commands = (
        command
        for command in tree.get_commands()
        if _supports_dm_context(command)
    )
    return tuple(sorted(_local_command_name(command) for command in commands))


def _require_application_id(tree: app_commands.CommandTree) -> int:
    application_id = tree.client.application_id
    if application_id is None:
        raise RuntimeError("La aplicacion aun no tiene application_id disponible.")

    return application_id


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


async def sync_dm_commands_globally(
        tree: app_commands.CommandTree,
) -> SyncReport:
    application_id = _require_application_id(tree)
    commands = [
        command
        for command in tree.get_commands()
        if _supports_dm_context(command)
    ]

    translator = tree.translator
    if translator:
        payload = [
            await command.get_translated_payload(tree, translator)
            for command in commands
        ]
    else:
        payload = [command.to_dict(tree) for command in commands]

    synced_commands = await tree.client.http.bulk_upsert_global_commands(
        application_id,
        payload=payload,
    )
    return SyncReport(
        scope="global",
        command_names=tuple(
            _synced_http_command_name(command)
            for command in synced_commands
        ),
    )


async def prune_command_scope(
        tree: app_commands.CommandTree,
        prune_scope: Literal["guild", "global"],
        guild_id: int | None,
) -> PruneReport:
    application_id = _require_application_id(tree)

    # Bulk overwrite with an empty payload to remove stale registrations in the target scope.
    if prune_scope == "guild":
        if guild_id is None:
            raise ValueError("No se pueden purgar comandos de guild sin DISCORD_GUILD_ID.")

        guild = discord.Object(id=guild_id)
        existing_commands = await tree.fetch_commands(guild=guild)
        await tree.client.http.bulk_upsert_guild_commands(
            application_id,
            guild_id,
            payload=[],
        )
        return PruneReport(
            scope="guild",
            guild_id=guild_id,
            deleted_command_names=tuple(command.name for command in existing_commands),
        )

    existing_commands = await tree.fetch_commands()
    await tree.client.http.bulk_upsert_global_commands(
        application_id,
        payload=[],
    )
    return PruneReport(
        scope="global",
        deleted_command_names=tuple(command.name for command in existing_commands),
    )
