from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from bigness_league_bot.application.services.tickets import (
    build_dm_message_link,
    build_guild_message_link,
    require_ticket_category,
)
from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelManagementError,
    ensure_allowed_member,
)
from bigness_league_bot.infrastructure.discord.tickets import (
    TicketIntegrationError,
    TicketStateStore,
    build_thread_tags_with_status,
    resolve_ticket_status_tag,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.views.ticket_message_embeds import (
    build_ticket_close_embed,
)

if TYPE_CHECKING:
    from bigness_league_bot.application.services.tickets import (
        TicketParticipant,
        TicketRecord,
    )
    from bigness_league_bot.infrastructure.discord.bot import BignessLeagueBot


@dataclass(frozen=True, slots=True)
class ResolvedTicketCloseContext:
    record: TicketRecord
    thread: discord.Thread
    is_dm_interaction: bool


async def execute_ticket_close(
        *,
        store: TicketStateStore,
        interaction: discord.Interaction[BignessLeagueBot],
        close_reason: str | None,
) -> None:
    resolved_context = await resolve_close_context(
        store=store,
        interaction=interaction,
    )
    if resolved_context is None:
        return

    closed_record = await close_ticket_thread(
        bot=interaction.client,
        store=store,
        thread=resolved_context.thread,
        record=resolved_context.record,
        closed_by=interaction.user,
        locale=interaction.locale,
        close_reason=close_reason,
        is_dm_interaction=resolved_context.is_dm_interaction,
        origin_dm_channel=(
            interaction.channel
            if isinstance(interaction.channel, discord.DMChannel)
            else None
        ),
    )
    if closed_record is None:
        await send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.not_active,
                locale=interaction.locale,
            ),
            ephemeral=interaction.guild is not None,
        )
        return

    if not resolved_context.is_dm_interaction:
        await send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.closed_ephemeral,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )


async def close_ticket_thread(
        *,
        bot: BignessLeagueBot,
        store: TicketStateStore,
        thread: discord.Thread,
        record: TicketRecord,
        closed_by: discord.abc.User | discord.Member,
        locale: str | discord.Locale | None,
        close_reason: str | None,
        is_dm_interaction: bool = False,
        origin_dm_channel: discord.DMChannel | None = None,
) -> TicketRecord | None:
    closed_record = store.close_thread(record.thread_id)
    if closed_record is None or closed_record.closed_at is None:
        return None

    category_label = _resolve_category_label(closed_record)
    thread_ticket_link = build_guild_message_link(
        guild_id=thread.guild.id,
        channel_id=thread.id,
        message_id=closed_record.thread_start_message_id,
    )
    thread_close_embed = build_ticket_close_embed(
        bot=bot,
        locale=locale,
        guild=thread.guild,
        closed_by=closed_by,
        category_label=category_label,
        ticket_number=closed_record.ticket_number,
        ticket_link=thread_ticket_link,
        created_at=closed_record.created_at,
        closed_at=closed_record.closed_at,
        close_reason=close_reason,
    )
    await thread.send(
        embed=thread_close_embed,
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
            replied_user=False,
        ),
    )

    await _send_close_dm(
        bot=bot,
        locale=locale,
        record=closed_record,
        category_label=category_label,
        guild=thread.guild,
        closed_by=closed_by,
        is_dm_interaction=is_dm_interaction,
        origin_dm_channel=origin_dm_channel,
        close_reason=close_reason,
    )
    await _disable_ticket_start_controls(
        store=store,
        bot=bot,
        record=closed_record,
        thread=thread,
    )

    await thread.edit(
        applied_tags=_build_closed_thread_tags(thread),
        reason=f"{closed_by} ({closed_by.id}) actualizo tags de ticket={thread.id}",
    )
    await thread.edit(
        archived=True,
        locked=True,
        reason=f"{closed_by} ({closed_by.id}) cerro publicacion ticket={thread.id}",
    )
    return closed_record


async def resolve_close_context(
        *,
        store: TicketStateStore,
        interaction: discord.Interaction[BignessLeagueBot],
) -> ResolvedTicketCloseContext | None:
    if interaction.guild is None:
        record = store.active_for_user(interaction.user.id)
        if record is None:
            await send_interaction_message(
                interaction,
                interaction.client.localizer.translate(
                    I18N.messages.tickets.close.not_active,
                    locale=interaction.locale,
                ),
            )
            return None

        thread = await _resolve_thread(interaction, record.thread_id)
        if thread is None:
            store.remove_thread(record.thread_id)
            await send_interaction_message(
                interaction,
                interaction.client.localizer.translate(
                    I18N.messages.tickets.close.not_active,
                    locale=interaction.locale,
                ),
            )
            return None

        return ResolvedTicketCloseContext(
            record=record,
            thread=thread,
            is_dm_interaction=True,
        )

    if not isinstance(interaction.user, discord.Member):
        await send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.errors.channel_management.server_only,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    try:
        ensure_allowed_member(interaction.user)
    except ChannelManagementError as error:
        await send_interaction_message(
            interaction,
            interaction.client.localizer.render(
                error.message,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    thread = interaction.channel
    if not isinstance(thread, discord.Thread):
        await send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.not_ticket_thread,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    record = store.active_for_thread(thread.id)
    if record is None:
        await send_interaction_message(
            interaction,
            interaction.client.localizer.translate(
                I18N.messages.tickets.close.not_active,
                locale=interaction.locale,
            ),
            ephemeral=True,
        )
        return None

    return ResolvedTicketCloseContext(
        record=record,
        thread=thread,
        is_dm_interaction=False,
    )


async def send_interaction_message(
        interaction: discord.Interaction[BignessLeagueBot],
        message: str,
        *,
        ephemeral: bool = False,
) -> None:
    if interaction.response.is_done():
        if interaction.guild is None:
            await interaction.followup.send(message)
            return

        await interaction.followup.send(message, ephemeral=ephemeral)
        return

    if interaction.guild is None:
        await interaction.response.send_message(message)
        return

    await interaction.response.send_message(message, ephemeral=ephemeral)


async def _send_close_dm(
        *,
        bot: BignessLeagueBot,
        locale: str | discord.Locale | None,
        record: TicketRecord,
        category_label: str,
        guild: discord.Guild,
        closed_by: discord.abc.User | discord.Member,
        is_dm_interaction: bool,
        origin_dm_channel: discord.DMChannel | None,
        close_reason: str | None,
) -> None:
    for participant in record.participants:
        try:
            dm_ticket_link = build_dm_message_link(
                channel_id=participant.dm_channel_id,
                message_id=participant.dm_start_message_id,
            )
            close_embed = build_ticket_close_embed(
                bot=bot,
                locale=locale,
                guild=guild,
                closed_by=closed_by,
                category_label=category_label,
                ticket_number=record.ticket_number,
                ticket_link=dm_ticket_link,
                created_at=record.created_at,
                closed_at=record.closed_at or record.created_at,
                close_reason=close_reason,
            )
            if (
                    is_dm_interaction
                    and closed_by.id == participant.user_id
                    and origin_dm_channel is not None
            ):
                await origin_dm_channel.send(embed=close_embed)
                continue

            ticket_user = await bot.fetch_user(participant.user_id)
            await ticket_user.send(embed=close_embed)
        except discord.HTTPException:
            continue


async def _disable_ticket_start_controls(
        *,
        store: TicketStateStore,
        bot: BignessLeagueBot,
        record: TicketRecord,
        thread: discord.Thread,
) -> None:
    await _disable_message_controls(
        channel=thread,
        message_id=record.thread_start_message_id,
        store=store,
    )
    for participant in record.participants:
        dm_channel = await _resolve_dm_channel(
            bot=bot,
            participant=participant,
        )
        if dm_channel is None:
            continue

        await _disable_message_controls(
            channel=dm_channel,
            message_id=participant.dm_start_message_id,
            store=store,
        )


async def _resolve_dm_channel(
        *,
        bot: BignessLeagueBot,
        participant: TicketParticipant,
) -> discord.DMChannel | None:
    if participant.dm_channel_id is not None:
        cached_channel = bot.get_channel(participant.dm_channel_id)
        if isinstance(cached_channel, discord.DMChannel):
            return cached_channel

    try:
        ticket_user = await bot.fetch_user(participant.user_id)
        return await ticket_user.create_dm()
    except discord.HTTPException:
        return None


async def _disable_message_controls(
        *,
        channel: discord.abc.Messageable,
        message_id: int | None,
        store: TicketStateStore,
) -> None:
    if message_id is None:
        return

    try:
        message = await channel.fetch_message(message_id)
        from bigness_league_bot.presentation.discord.views.ticket_thread_controls import (
            TicketThreadControlsView,
        )

        await message.edit(view=TicketThreadControlsView(store, disabled=True))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        return


def _build_closed_thread_tags(
        thread: discord.Thread,
):
    forum_channel = thread.parent
    if not isinstance(forum_channel, discord.ForumChannel):
        return discord.utils.MISSING

    try:
        closed_status_tag = resolve_ticket_status_tag(
            forum_channel,
            is_closed=True,
        )
    except TicketIntegrationError:
        return discord.utils.MISSING

    return build_thread_tags_with_status(
        thread,
        status_tag=closed_status_tag,
    )


def _resolve_category_label(record: TicketRecord) -> str:
    try:
        return require_ticket_category(record.category_key).label
    except ValueError:
        return record.category_key


async def _resolve_thread(
        interaction: discord.Interaction[BignessLeagueBot],
        thread_id: int,
) -> discord.Thread | None:
    channel = interaction.client.get_channel(thread_id)
    if isinstance(channel, discord.Thread):
        return channel

    try:
        fetched_channel = await interaction.client.fetch_channel(thread_id)
    except discord.HTTPException:
        return None

    if isinstance(fetched_channel, discord.Thread):
        return fetched_channel

    return None
