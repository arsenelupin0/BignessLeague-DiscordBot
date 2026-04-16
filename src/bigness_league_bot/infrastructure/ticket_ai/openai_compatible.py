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
import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from bigness_league_bot.infrastructure.ticket_ai.ollama import OllamaClientError


@dataclass(frozen=True, slots=True)
class OpenAiCompatibleChatMessage:
    role: str
    content: str


class OpenAiCompatibleClient:
    def __init__(
            self,
            *,
            base_url: str,
            api_key: str,
            model: str,
            timeout_seconds: int,
            temperature: float,
            max_output_tokens: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    async def chat_json(
            self,
            *,
            messages: tuple[OpenAiCompatibleChatMessage, ...],
            json_schema: dict[str, object],
    ) -> dict[str, Any]:
        payload = self._build_chat_payload(
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ticket_ai_response",
                    "strict": True,
                    "schema": json_schema,
                },
            },
        )
        try:
            response_payload = await asyncio.to_thread(
                self._post_json,
                "/chat/completions",
                payload,
            )
        except OllamaClientError:
            fallback_payload = self._build_chat_payload(
                messages=messages,
                response_format={"type": "json_object"},
            )
            response_payload = await asyncio.to_thread(
                self._post_json,
                "/chat/completions",
                fallback_payload,
            )

        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OllamaClientError("El servidor OpenAI-compatible no ha devuelto `choices` validos.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise OllamaClientError("La primera opcion de respuesta no es valida.")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise OllamaClientError("La respuesta no contiene un objeto `message` valido.")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaClientError("La respuesta del modelo no contiene texto util.")

        try:
            parsed_payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaClientError(
                "La respuesta del modelo no es un JSON valido."
            ) from exc

        if not isinstance(parsed_payload, dict):
            raise OllamaClientError("La respuesta JSON del modelo no es un objeto.")

        return parsed_payload

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self._get_json, "/models")
        except OllamaClientError:
            return False

        return True

    def _build_chat_payload(
            self,
            *,
            messages: tuple[OpenAiCompatibleChatMessage, ...],
            response_format: dict[str, object],
    ) -> dict[str, object]:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "stream": False,
            "response_format": response_format,
        }

    def _get_json(
            self,
            path: str,
    ) -> dict[str, Any]:
        http_request = request.Request(
            url=f"{self.base_url}{path}",
            headers=self._headers(),
            method="GET",
        )
        return self._perform_request(http_request)

    def _post_json(
            self,
            path: str,
            payload: dict[str, object],
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            headers=self._headers(),
            method="POST",
        )
        return self._perform_request(http_request)

    def _perform_request(
            self,
            http_request: request.Request,
    ) -> dict[str, Any]:
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace").strip()
            raise OllamaClientError(
                f"El servidor OpenAI-compatible devolvio HTTP {exc.code}: {details or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise OllamaClientError(
                f"No se puede conectar con {self.base_url}: {exc.reason}"
            ) from exc

        try:
            parsed_payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise OllamaClientError(
                "La respuesta del servidor OpenAI-compatible no es JSON valido."
            ) from exc

        if not isinstance(parsed_payload, dict):
            raise OllamaClientError("El servidor OpenAI-compatible ha devuelto un payload invalido.")

        error_payload = parsed_payload.get("error")
        if isinstance(error_payload, dict):
            message = error_payload.get("message")
            if isinstance(message, str) and message.strip():
                raise OllamaClientError(message.strip())
        if isinstance(error_payload, str) and error_payload.strip():
            raise OllamaClientError(error_payload.strip())

        return parsed_payload

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers
