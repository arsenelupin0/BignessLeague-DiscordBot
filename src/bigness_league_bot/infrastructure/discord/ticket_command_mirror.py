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

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import TicketRecord
from bigness_league_bot.infrastructure.discord.ticket_relay_messages import (
    attachment_signature,
    build_ticket_command_relay_message,
    clone_message_attachments_as_files,
    clone_message_embeds,
    message_body,
)
from bigness_league_bot.infrastructure.discord.tickets import TicketStateStore
from bigness_league_bot.infrastructure.i18n.keys import I18N

if TYPE_CHECKING:
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot

LOGGER = logging.getLogger(__name__)
ResolveTicketUser = Callable[[int], Awaitable[discord.User | None]]
SendDm = Callable[..., Awaitable[discord.Message]]


class TicketCommandMirror:
    def __init__(
            self,
            *,
            bot: BignessLeagueBot,
            store: TicketStateStore,
            resolve_ticket_user: ResolveTicketUser,
            send_dm: SendDm,
    ) -> None:
        self.bot = bot
        self.store = store
        self._resolve_ticket_user = resolve_ticket_user
        self._send_dm = send_dm
        self._interaction_command_names: dict[int, str] = {}
        self._thread_to_dm_message_ids: dict[int, dict[int, int]] = {}
        self._thread_to_dm_message_locks: dict[int, asyncio.Lock] = {}
        self._thread_command_name_overrides: dict[int, str] = {}
        self._thread_to_dm_message_signatures: dict[int, tuple[object, ...]] = {}

    def remember_interaction_command(
            self,
            interaction: discord.Interaction[BignessLeagueBot],
    ) -> None:
        if interaction.type != discord.InteractionType.application_command:
            return

        command = interaction.command
        if command is None:
            return

        qualified_name = getattr(command, "qualified_name", None)
        if isinstance(qualified_name, str) and qualified_name.strip():
            self._interaction_command_names[interaction.id] = qualified_name.strip()
            return

        name = getattr(command, "name", None)
        if isinstance(name, str) and name.strip():
            self._interaction_command_names[interaction.id] = name.strip()

    def has_thread_message(self, message_id: int) -> bool:
        return message_id in self._thread_to_dm_message_ids

    async def mirror_thread_command_message(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        async with self._message_lock(message.id):
            return await self._mirror_thread_command_message_locked(
                message,
                command_name=command_name,
            )

    async def _mirror_thread_command_message_locked(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        self._remember_command_name_override(message, command_name=command_name)
        record = self.store.active_for_thread(message.channel.id)
        if record is None:
            return None
        if self.has_thread_message(message.id):
            return await self._mirror_thread_command_message_edit_locked(
                message,
                command_name=command_name,
            )

        relay_signature = self.build_relay_signature(
            message,
            command_name=command_name,
        )

        dm_message_ids = self._thread_to_dm_message_ids.setdefault(message.id, {})
        latest_dm_message: discord.Message | None = None
        failed_user_ids: list[int] = []
        for participant_id in record.participant_ids:
            try:
                ticket_user = await self._resolve_ticket_user(participant_id)
                if ticket_user is None:
                    failed_user_ids.append(participant_id)
                    continue
                dm_message = await self._send_dm(
                    ticket_user,
                    **await self._build_send_kwargs(
                        message,
                        command_name=command_name,
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                dm_message_ids[participant_id] = dm_message.id
                latest_dm_message = dm_message
            except discord.Forbidden:
                failed_user_ids.append(participant_id)
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_BOT_COMMAND_RELAY_FAILED thread=%s user_id=%s message=%s",
                    message.channel.id,
                    participant_id,
                    message.id,
                )

        if failed_user_ids:
            await self._notify_failed_recipients(message, failed_user_ids)

        if latest_dm_message is None:
            return None

        self._thread_to_dm_message_signatures[message.id] = relay_signature
        return latest_dm_message

    async def mirror_thread_command_message_edit(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        async with self._message_lock(message.id):
            return await self._mirror_thread_command_message_edit_locked(
                message,
                command_name=command_name,
            )

    async def _mirror_thread_command_message_edit_locked(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> discord.Message | None:
        self._remember_command_name_override(message, command_name=command_name)
        record = self.store.active_for_thread(message.channel.id)
        if record is None:
            return None

        dm_message_ids = self._thread_to_dm_message_ids.get(message.id)
        if not dm_message_ids:
            return await self._mirror_thread_command_message_locked(
                message,
                command_name=command_name,
            )

        relay_signature = self.build_relay_signature(
            message,
            command_name=command_name,
        )
        previous_signature = self._thread_to_dm_message_signatures.get(message.id)

        latest_dm_message: discord.Message | None = None
        failed_user_ids: list[int] = []
        for participant in record.participants:
            try:
                ticket_user = await self._resolve_ticket_user(participant.user_id)
                if ticket_user is None:
                    failed_user_ids.append(participant.user_id)
                    continue
                dm_channel = await ticket_user.create_dm()
                dm_message_id = dm_message_ids.get(participant.user_id)
                if previous_signature == relay_signature and dm_message_id is not None:
                    latest_dm_message = await dm_channel.fetch_message(dm_message_id)
                    continue
                if dm_message_id is None:
                    sent_dm_message = await self._send_dm(
                        ticket_user,
                        **await self._build_send_kwargs(
                            message,
                            command_name=command_name,
                        ),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    dm_message_ids[participant.user_id] = sent_dm_message.id
                    latest_dm_message = sent_dm_message
                    continue
                dm_message = await dm_channel.fetch_message(dm_message_id)
                await dm_message.edit(
                    **await self._build_edit_kwargs(
                        message,
                        dm_message=dm_message,
                        command_name=command_name,
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                    view=None,
                )
                latest_dm_message = dm_message
            except discord.NotFound:
                dm_message_ids.pop(participant.user_id, None)
                replacement_dm_message = await self.send_result_to_participant(
                    record=record,
                    participant_id=participant.user_id,
                    message=message,
                    command_name=command_name,
                )
                if replacement_dm_message is not None:
                    dm_message_ids[participant.user_id] = replacement_dm_message.id
                    latest_dm_message = replacement_dm_message
            except discord.Forbidden:
                failed_user_ids.append(participant.user_id)
            except discord.HTTPException:
                LOGGER.exception(
                    "TICKET_BOT_COMMAND_RELAY_EDIT_FAILED thread=%s user_id=%s message=%s dm_message=%s",
                    message.channel.id,
                    participant.user_id,
                    message.id,
                    dm_message_ids.get(participant.user_id),
                )

        if failed_user_ids:
            await self._notify_failed_recipients(message, failed_user_ids)

        if latest_dm_message is None:
            return None

        self._thread_to_dm_message_signatures[message.id] = relay_signature
        self._thread_to_dm_message_ids[message.id] = dm_message_ids
        return latest_dm_message

    async def send_result_to_participant(
            self,
            *,
            record: TicketRecord,
            participant_id: int,
            message: discord.Message,
            command_name: str | None = None,
    ) -> discord.Message | None:
        ticket_user = await self._resolve_ticket_user(participant_id)
        if ticket_user is None:
            return None

        try:
            return await self._send_dm(
                ticket_user,
                **await self._build_send_kwargs(
                    message,
                    command_name=command_name,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            await self._notify_failed_recipients(message, [participant_id])
            return None
        except discord.HTTPException:
            LOGGER.exception(
                "TICKET_BOT_COMMAND_RELAY_FAILED thread=%s user_id=%s message=%s",
                record.thread_id,
                participant_id,
                message.id,
            )
            return None

    def remember_participant_message(
            self,
            *,
            thread_message_id: int,
            participant_id: int,
            dm_message_id: int,
            message: discord.Message,
            command_name: str | None = None,
    ) -> None:
        self._thread_to_dm_message_ids.setdefault(
            thread_message_id,
            {},
        )[participant_id] = dm_message_id
        self._thread_to_dm_message_signatures[thread_message_id] = (
            self.build_relay_signature(message, command_name=command_name)
        )

    def _message_lock(self, message_id: int) -> asyncio.Lock:
        lock = self._thread_to_dm_message_locks.get(message_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_to_dm_message_locks[message_id] = lock

        return lock

    def _remember_command_name_override(
            self,
            message: discord.Message,
            *,
            command_name: str | None,
    ) -> None:
        if command_name is None:
            return

        normalized_name = command_name.strip()
        if not normalized_name:
            return

        self._thread_command_name_overrides[message.id] = normalized_name

    def _resolved_command_name(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> str:
        if command_name is not None and command_name.strip():
            return command_name.strip()

        overridden_name = self._thread_command_name_overrides.get(message.id)
        if overridden_name:
            return overridden_name

        return self._interaction_command_name(message) or "comando"

    def _interaction_command_name(self, message: discord.Message) -> str | None:
        interaction_metadata = message.interaction_metadata
        if interaction_metadata is None:
            return None

        interaction_id = getattr(interaction_metadata, "id", None)
        if isinstance(interaction_id, int):
            resolved_name = self._interaction_command_names.get(interaction_id)
            if resolved_name:
                return resolved_name

        name = getattr(interaction_metadata, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()

        return None

    def build_relay_signature(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> tuple[object, ...]:
        return (
            self._resolved_command_name(message, command_name=command_name),
            message_body(
                localizer=self.bot.localizer,
                message=message,
                attachment_mode="names",
            ),
            tuple(embed.to_dict() for embed in message.embeds),
            attachment_signature(message.attachments),
        )

    async def _build_send_kwargs(
            self,
            message: discord.Message,
            *,
            command_name: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "content": build_ticket_command_relay_message(
                localizer=self.bot.localizer,
                message=message,
                command_name=self._resolved_command_name(
                    message,
                    command_name=command_name,
                ),
            ),
            "embeds": clone_message_embeds(message),
        }
        files = await clone_message_attachments_as_files(message)
        if files:
            payload["files"] = files

        return payload

    async def _build_edit_kwargs(
            self,
            message: discord.Message,
            *,
            dm_message: discord.Message,
            command_name: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "content": build_ticket_command_relay_message(
                localizer=self.bot.localizer,
                message=message,
                command_name=self._resolved_command_name(
                    message,
                    command_name=command_name,
                ),
            ),
            "embeds": clone_message_embeds(message),
        }
        source_attachments = attachment_signature(message.attachments)
        mirrored_attachments = attachment_signature(dm_message.attachments)
        if not source_attachments:
            payload["attachments"] = []
        elif source_attachments != mirrored_attachments:
            payload["attachments"] = await clone_message_attachments_as_files(message)

        return payload

    async def _notify_failed_recipients(
            self,
            message: discord.Message,
            failed_user_ids: list[int],
    ) -> None:
        await message.channel.send(
            self.bot.localizer.translate(
                I18N.messages.tickets.relay.dm_failed_for_staff,
                user_id=", ".join(str(user_id) for user_id in failed_user_ids),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )
