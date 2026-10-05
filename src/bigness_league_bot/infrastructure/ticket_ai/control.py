from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace

from bigness_league_bot.application.services.ticket_ai import (
    TicketAiConversationTurn,
    TicketAiReply,
    TicketAiService,
)
from bigness_league_bot.core.settings import Settings

LOGGER = logging.getLogger(__name__)


class TicketAiControl:
    """Persistent global switch with lazy loading and cancellation of pending replies."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state_path = settings.ticket_state_file.with_name(
            f"{settings.ticket_state_file.stem}_ai.json"
        )
        self.enabled = self._load_enabled()
        self.service: TicketAiService | None = None
        self._pending: set[asyncio.Task[TicketAiReply]] = set()

    def get_service(self) -> TicketAiService | None:
        if not self.enabled:
            return None
        if self.service is None:
            self.service = self._create_service()
        return self.service

    def is_current(self, service: TicketAiService) -> bool:
        return self.enabled and self.service is service

    def set_enabled(self, enabled: bool) -> None:
        # Validate local resources before persisting an activation. No backend request.
        service = (self.service or self._create_service()) if enabled else None
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps({"enabled": enabled}, indent=2), encoding="utf-8"
        )
        temporary_path.replace(self.state_path)
        self.enabled = enabled
        self.service = service
        if not enabled:
            for task in tuple(self._pending):
                task.cancel()
        LOGGER.info("TICKET_AI_GLOBAL_SWITCH enabled=%s path=%s", enabled, self.state_path)

    async def generate_reply(
            self,
            *,
            service: TicketAiService,
            category_key: str,
            latest_user_message: str,
            conversation: tuple[TicketAiConversationTurn, ...],
    ) -> TicketAiReply | None:
        if not self.is_current(service):
            return None
        task = asyncio.create_task(service.generate_reply(
            category_key=category_key,
            latest_user_message=latest_user_message,
            conversation=conversation,
        ))
        self._pending.add(task)
        try:
            reply = await task
            return reply if self.is_current(service) else None
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if not self.is_current(service) and caller is not None and not caller.cancelling():
                return None
            raise
        finally:
            self._pending.discard(task)

    def _create_service(self) -> TicketAiService:
        service = TicketAiService.from_settings(replace(
            self.settings, ticket_ai_enabled=True, ticket_ai_auto_reply_enabled=True,
        ))
        assert service is not None
        return service

    def _load_enabled(self) -> bool:
        if self.state_path.exists():
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("enabled"), bool):
                    return payload["enabled"]
                raise ValueError("El estado global de IA debe contener enabled como booleano.")
            except (OSError, ValueError):
                # An invalid saved switch must never reactivate AI unexpectedly.
                LOGGER.exception("TICKET_AI_STATE_LOAD_FAILED path=%s", self.state_path)
                return False
        return self.settings.ticket_ai_enabled and self.settings.ticket_ai_auto_reply_enabled
