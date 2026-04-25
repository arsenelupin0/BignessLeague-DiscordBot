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
from pathlib import Path
from typing import Any, Literal, Protocol

from bigness_league_bot.application.services.tickets import normalize_ticket_category_key
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.ticket_ai.knowledge_base import (
    TicketAiKnowledgeBase,
    TicketAiKnowledgeMatch,
)
from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaClient
from bigness_league_bot.infrastructure.ticket_ai.ollama import (
    OllamaClientError,
)
from bigness_league_bot.infrastructure.ticket_ai.openai_compatible import (
    OpenAiCompatibleChatMessage,
    OpenAiCompatibleClient,
)

ConversationRole = Literal["user", "staff", "assistant"]
HUMAN_ESCALATION_PHRASES: tuple[str, ...] = (
    "escalar este ticket",
    "escala este ticket",
    "puedes escalar este ticket",
    "quiero que lo revise una persona",
    "quiero que lo revise alguien",
    "quiero hablar con una persona",
    "quiero hablar con alguien",
    "quiero hablar con staff",
    "quiero hablar con el staff",
    "necesito ayuda de una persona",
    "necesito ayuda real",
    "necesito ayuda humana",
    "necesito soporte humano",
    "necesito a un administrador",
    "necesito a alguien del staff",
    "necesito a una persona del staff",
    "que alguien del staff revise esto",
    "que un administrador revise esto",
    "que una persona revise esto",
)


class TicketAiChatClient(Protocol):
    async def chat_json(
            self,
            *,
            messages: Any,
            json_schema: dict[str, object],
    ) -> dict[str, Any]:
        ...

    async def ping(self) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class TicketAiConversationTurn:
    role: ConversationRole
    content: str


@dataclass(frozen=True, slots=True)
class TicketAiReply:
    answer: str
    confidence: int
    should_escalate: bool
    reason: str
    used_entry_ids: tuple[str, ...]
    retrieved_matches: tuple[TicketAiKnowledgeMatch, ...]


class TicketAiService:
    def __init__(
            self,
            *,
            settings: Settings,
            ai_client: TicketAiChatClient,
            knowledge_base: TicketAiKnowledgeBase,
            system_prompt: str,
    ) -> None:
        self.settings = settings
        self.ai_client = ai_client
        self.knowledge_base = knowledge_base
        self.system_prompt = system_prompt.strip()

    @classmethod
    def from_settings(cls, settings: Settings) -> "TicketAiService | None":
        if not settings.ticket_ai_enabled:
            return None

        knowledge_base = TicketAiKnowledgeBase.from_file(
            settings.ticket_ai_knowledge_base_file
        )
        system_prompt = _load_prompt(settings.ticket_ai_system_prompt_file)
        ai_client = create_ticket_ai_chat_client(settings)
        return cls(
            settings=settings,
            ai_client=ai_client,
            knowledge_base=knowledge_base,
            system_prompt=system_prompt,
        )

    def can_auto_reply(self, category_key: str) -> bool:
        if not self.settings.ticket_ai_auto_reply_enabled:
            return False

        normalized_category_key = normalize_ticket_category_key(category_key)
        if self.is_force_escalate_category(normalized_category_key):
            return False

        return normalized_category_key in self._normalized_autoreply_categories()

    def is_force_escalate_category(self, category_key: str) -> bool:
        normalized_category_key = normalize_ticket_category_key(category_key)
        return normalized_category_key in self._normalized_force_escalate_categories()

    async def generate_reply(
            self,
            *,
            category_key: str,
            latest_user_message: str,
            conversation: tuple[TicketAiConversationTurn, ...],
    ) -> TicketAiReply:
        requested_human_support = detect_human_support_request(latest_user_message)
        matches = self.knowledge_base.search(
            query=latest_user_message,
            category=category_key,
            limit=self.settings.ticket_ai_max_knowledge_matches,
            max_characters=self.settings.ticket_ai_max_knowledge_characters,
        )
        prompt_messages = (
            self._build_message(
                role="system",
                content=self.system_prompt,
            ),
            self._build_message(
                role="user",
                content=_build_model_input(
                    category_key=category_key,
                    latest_user_message=latest_user_message,
                    conversation=conversation[-self.settings.ticket_ai_max_context_messages:],
                    matches=matches,
                    requested_human_support=requested_human_support,
                ),
            ),
        )
        response_payload = await self.ai_client.chat_json(
            messages=prompt_messages,
            json_schema=_ticket_ai_json_schema(),
        )
        return _parse_ticket_ai_reply(
            payload=response_payload,
            retrieved_matches=matches,
            force_escalate_category=self.is_force_escalate_category(category_key),
            requested_human_support=requested_human_support,
        )

    async def ping(self) -> bool:
        return await self.ai_client.ping()

    def _build_message(
            self,
            *,
            role: str,
            content: str,
    ) -> object:
        if self.settings.ticket_ai_provider == "openai_compatible":
            return OpenAiCompatibleChatMessage(
                role=role,
                content=content,
            )

        from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaChatMessage

        return OllamaChatMessage(
            role=role,
            content=content,
        )

    def _normalized_autoreply_categories(self) -> frozenset[str]:
        return frozenset(
            normalize_ticket_category_key(category_key)
            for category_key in self.settings.ticket_ai_autoreply_categories
        )

    def _normalized_force_escalate_categories(self) -> frozenset[str]:
        return frozenset(
            normalize_ticket_category_key(category_key)
            for category_key in self.settings.ticket_ai_force_escalate_categories
        )


def create_ticket_ai_chat_client(settings: Settings) -> TicketAiChatClient:
    if settings.ticket_ai_provider == "openai_compatible":
        return OpenAiCompatibleClient(
            base_url=settings.ticket_ai_base_url,
            api_key=settings.ticket_ai_api_key,
            model=settings.ticket_ai_model,
            timeout_seconds=settings.ticket_ai_request_timeout_seconds,
            temperature=settings.ticket_ai_temperature,
            max_output_tokens=settings.ticket_ai_max_output_tokens,
        )

    return OllamaClient(
        base_url=settings.ticket_ai_base_url,
        model=settings.ticket_ai_model,
        timeout_seconds=settings.ticket_ai_request_timeout_seconds,
        keep_alive=settings.ticket_ai_keep_alive,
        temperature=settings.ticket_ai_temperature,
    )


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _build_model_input(
        *,
        category_key: str,
        latest_user_message: str,
        conversation: tuple[TicketAiConversationTurn, ...],
        matches: tuple[TicketAiKnowledgeMatch, ...],
        requested_human_support: bool,
) -> str:
    conversation_blocks = [
        f"- {turn.role}: {turn.content.strip()}"
        for turn in conversation
        if turn.content.strip()
    ]
    knowledge_blocks = [
        match.snippet
        for match in matches
    ]
    if not knowledge_blocks:
        knowledge_blocks.append("Sin resultados relevantes en la base de conocimiento.")

    return "\n\n".join(
        [
            f"Categoría del ticket: {category_key}",
            (
                    "El usuario ha pedido atención humana o escalar el ticket: "
                    + ("si" if requested_human_support else "no")
            ),
            f"Ultimo mensaje del usuario:\n{latest_user_message.strip()}",
            (
                "Contexto reciente del ticket:\n"
                + "\n".join(conversation_blocks)
                if conversation_blocks
                else "Contexto reciente del ticket:\n- (sin mensajes previos)"
            ),
            "Base de conocimiento recuperada:\n" + "\n\n".join(knowledge_blocks),
        ]
    )


def _ticket_ai_json_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "integer"},
            "should_escalate": {"type": "boolean"},
            "reason": {"type": "string"},
            "used_entry_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "answer",
            "confidence",
            "should_escalate",
            "reason",
            "used_entry_ids",
        ],
    }


def _parse_ticket_ai_reply(
        *,
        payload: dict[str, object],
        retrieved_matches: tuple[TicketAiKnowledgeMatch, ...],
        force_escalate_category: bool = False,
        requested_human_support: bool = False,
) -> TicketAiReply:
    answer = _read_text(payload.get("answer"))
    if not answer:
        raise OllamaClientError("La IA local no ha devuelto un texto de respuesta.")

    confidence = _read_confidence(payload.get("confidence", 0))

    should_escalate = requested_human_support
    reason = _read_text(payload.get("reason")) or "Sin motivo especificado."
    used_entry_ids_raw = payload.get("used_entry_ids", [])
    if isinstance(used_entry_ids_raw, list):
        used_entry_ids = tuple(
            entry_id
            for item in used_entry_ids_raw
            if (entry_id := _read_text(item))
        )
    else:
        used_entry_ids = ()

    if force_escalate_category:
        should_escalate = True
        if reason == "Sin motivo especificado.":
            reason = "La categoría del ticket requiere revisión de staff."

    if requested_human_support and reason == "Sin motivo especificado.":
        reason = "El usuario ha pedido atención de una persona del staff."

    return TicketAiReply(
        answer=answer,
        confidence=confidence,
        should_escalate=should_escalate,
        reason=reason,
        used_entry_ids=used_entry_ids,
        retrieved_matches=retrieved_matches,
    )


def _read_confidence(value: object) -> int:
    if isinstance(value, bool):
        raise OllamaClientError("La IA local ha devuelto una confianza inválida.")
    if isinstance(value, int):
        return max(0, min(100, value))
    if isinstance(value, float):
        return max(0, min(100, int(value)))
    if isinstance(value, str) and value.strip():
        try:
            return max(0, min(100, int(value.strip())))
        except ValueError as exc:
            raise OllamaClientError("La IA local ha devuelto una confianza inválida.") from exc

    raise OllamaClientError("La IA local ha devuelto una confianza inválida.")


def _read_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    return ""


def detect_human_support_request(message: str) -> bool:
    normalized_message = " ".join(message.casefold().split())
    return any(
        phrase in normalized_message
        for phrase in HUMAN_ESCALATION_PHRASES
    )
