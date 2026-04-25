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


class OllamaClientError(RuntimeError):
    """Raised when the local Ollama service cannot complete a request."""


@dataclass(frozen=True, slots=True)
class OllamaChatMessage:
    role: str
    content: str


class OllamaClient:
    def __init__(
            self,
            *,
            base_url: str,
            model: str,
            timeout_seconds: int,
            keep_alive: str,
            temperature: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.keep_alive = keep_alive
        self.temperature = temperature

    async def chat_json(
            self,
            *,
            messages: tuple[OllamaChatMessage, ...],
            json_schema: dict[str, object],
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "format": json_schema,
            "options": {
                "temperature": self.temperature,
            },
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ],
        }
        response_payload = await asyncio.to_thread(self._post_json, "/api/chat", payload)
        message = response_payload.get("message")
        if not isinstance(message, dict):
            raise OllamaClientError("Ollama no ha devuelto un objeto `message` válido.")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaClientError("Ollama no ha devuelto contenido útil en la respuesta.")

        try:
            parsed_payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaClientError("Ollama no ha devuelto un JSON válido.") from exc

        if not isinstance(parsed_payload, dict):
            raise OllamaClientError("Ollama ha devuelto un JSON que no es un objeto.")

        return parsed_payload

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self._post_json, "/api/generate", {"model": self.model})
        except OllamaClientError:
            return False

        return True

    def _post_json(
            self,
            path: str,
            payload: dict[str, object],
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace").strip()
            raise OllamaClientError(
                f"Ollama devolvió HTTP {exc.code}: {details or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise OllamaClientError(
                f"No se puede conectar con Ollama en {self.base_url}: {exc.reason}"
            ) from exc

        try:
            parsed_payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise OllamaClientError("La respuesta HTTP de Ollama no es JSON válido.") from exc

        if not isinstance(parsed_payload, dict):
            raise OllamaClientError("Ollama ha devuelto un payload inválido.")

        error_message = parsed_payload.get("error")
        if isinstance(error_message, str) and error_message.strip():
            raise OllamaClientError(error_message.strip())

        return parsed_payload
