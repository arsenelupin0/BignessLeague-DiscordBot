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

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from urllib import error, parse, request

from bigness_league_bot.application.services.match_replays import (
    MatchReplayGame,
    MatchReplayPlayer,
    MatchReplayTeam,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.infrastructure.i18n.keys import I18N

LOGGER = logging.getLogger(__name__)
_REQUEST_THROTTLE_LOCK = threading.Lock()
_LAST_REQUEST_MONOTONIC = 0.0


class BallchasingClientError(CommandUserError):
    """Raised when Ballchasing rejects or cannot process replay data."""


@dataclass(frozen=True, slots=True)
class BallchasingReplayUpload:
    filename: str
    content: bytes
    expected_size: int | None = None
    sha256: str = ""
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class BallchasingReplayGroup:
    id: str
    name: str


class BallchasingClient:
    def __init__(
            self,
            *,
            api_base_url: str,
            api_token: str,
            visibility: str,
            group_id: str | None,
            timeout_seconds: int,
            poll_interval_seconds: float,
            max_poll_attempts: int,
            min_request_interval_seconds: float,
            rate_limit_retry_seconds: float,
            rate_limit_max_retries: int,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_token = api_token.strip()
        self.visibility = visibility.strip() or "private"
        self.group_id = group_id.strip() if group_id is not None else None
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_attempts = max_poll_attempts
        self.min_request_interval_seconds = max(0.0, min_request_interval_seconds)
        self.rate_limit_retry_seconds = max(0.0, rate_limit_retry_seconds)
        self.rate_limit_max_retries = max(0, rate_limit_max_retries)

    async def upload_and_fetch_replay(
            self,
            upload: BallchasingReplayUpload,
            *,
            title: str,
            group_id: str | None = None,
    ) -> MatchReplayGame:
        if not self.api_token:
            raise BallchasingClientError(
                localize(I18N.errors.match_replays.ballchasing_token_missing)
            )

        LOGGER.info(
            "Subiendo replay a Ballchasing filename=%s size=%s expected_size=%s sha256=%s content_type=%s title=%s",
            upload.filename,
            len(upload.content),
            upload.expected_size,
            upload.sha256 or "-",
            upload.content_type or "-",
            title,
        )
        upload_payload = await asyncio.to_thread(
            self._upload_replay,
            upload,
            group_id,
        )
        replay_id = _extract_replay_id(upload_payload)
        LOGGER.info(
            "Replay subida a Ballchasing filename=%s replay_id=%s duplicate=%s",
            upload.filename,
            replay_id,
            _payload_str(upload_payload, "error").casefold() == "duplicate replay",
        )
        is_duplicate = _payload_str(upload_payload, "error").casefold() == "duplicate replay"
        metadata: dict[str, str] = {}
        if not is_duplicate:
            metadata["title"] = title
        if is_duplicate and group_id:
            metadata["group"] = group_id
        if metadata:
            await asyncio.to_thread(self._patch_replay_metadata, replay_id, metadata)
        replay_payload = await self._wait_for_replay(replay_id)
        return replace(
            _parse_replay_payload(replay_payload),
            replay_sha256=upload.sha256,
        )

    async def ensure_group_path(
            self,
            *,
            parent_group_id: str,
            group_names: Sequence[str],
    ) -> BallchasingReplayGroup:
        if not self.api_token:
            raise BallchasingClientError(
                localize(I18N.errors.match_replays.ballchasing_token_missing)
            )

        current_parent_id = parent_group_id.strip()
        if not current_parent_id:
            raise BallchasingClientError(
                localize(I18N.errors.match_replays.ballchasing_group_missing)
            )

        resolved_group = BallchasingReplayGroup(id=current_parent_id, name="")
        for group_name in group_names:
            normalized_name = group_name.strip()
            if not normalized_name:
                continue
            resolved_group = await asyncio.to_thread(
                self._ensure_child_group,
                current_parent_id,
                normalized_name,
            )
            current_parent_id = resolved_group.id
        return resolved_group

    async def _wait_for_replay(
            self,
            replay_id: str,
    ) -> dict[str, Any]:
        for attempt in range(1, self.max_poll_attempts + 1):
            payload = await asyncio.to_thread(self._get_replay, replay_id)
            status = _payload_str(payload, "status").casefold()
            LOGGER.info(
                "Consulta de replay Ballchasing replay_id=%s attempt=%s/%s status=%s has_blue=%s has_orange=%s title=%s",
                replay_id,
                attempt,
                self.max_poll_attempts,
                status or "unknown",
                isinstance(payload.get("blue"), dict),
                isinstance(payload.get("orange"), dict),
                _payload_str(payload, "title") or "-",
            )
            if status in {"failed", "error"}:
                LOGGER.warning(
                    "Ballchasing marco la replay como fallida replay_id=%s payload_keys=%s",
                    replay_id,
                    sorted(payload.keys()),
                )
                raise BallchasingClientError(
                    localize(
                        I18N.errors.match_replays.ballchasing_processing_failed,
                        replay_id=replay_id,
                    )
                )

            if _has_processed_score(payload):
                return payload

            if attempt < self.max_poll_attempts:
                await asyncio.sleep(self.poll_interval_seconds)

        raise BallchasingClientError(
            localize(
                I18N.errors.match_replays.ballchasing_processing_timeout,
                replay_id=replay_id,
            )
        )

    def _upload_replay(
            self,
            upload: BallchasingReplayUpload,
            group_id: str | None,
    ) -> dict[str, Any]:
        query: dict[str, str] = {
            "visibility": self.visibility,
        }
        resolved_group_id = group_id or self.group_id
        if resolved_group_id:
            query["group"] = resolved_group_id

        body, content_type = _build_multipart_body(
            field_name="file",
            filename=upload.filename,
            content=upload.content,
        )
        http_request = request.Request(
            url=f"{self.api_base_url}/v2/upload?{parse.urlencode(query)}",
            data=body,
            headers={
                "Authorization": self.api_token,
                "Content-Type": content_type,
            },
            method="POST",
        )
        return self._perform_request(http_request, allow_duplicate_replay=True)

    def _get_replay(
            self,
            replay_id: str,
    ) -> dict[str, Any]:
        http_request = request.Request(
            url=f"{self.api_base_url}/replays/{parse.quote(replay_id)}",
            headers={"Authorization": self.api_token},
            method="GET",
        )
        return self._perform_request(http_request)

    def _patch_replay_metadata(
            self,
            replay_id: str,
            metadata: dict[str, str],
    ) -> None:
        body = json.dumps(metadata).encode("utf-8")
        http_request = request.Request(
            url=f"{self.api_base_url}/replays/{parse.quote(replay_id)}",
            data=body,
            headers={
                "Authorization": self.api_token,
                "Content-Type": "application/json",
            },
            method="PATCH",
        )
        self._perform_empty_request(http_request)

    def _ensure_child_group(
            self,
            parent_group_id: str,
            group_name: str,
    ) -> BallchasingReplayGroup:
        existing_group = self._find_child_group(parent_group_id, group_name)
        if existing_group is not None:
            return existing_group
        return self._create_group(parent_group_id=parent_group_id, group_name=group_name)

    def _find_child_group(
            self,
            parent_group_id: str,
            group_name: str,
    ) -> BallchasingReplayGroup | None:
        query = parse.urlencode(
            {
                "group": parent_group_id,
                "name": group_name,
                "count": "200",
            }
        )
        http_request = request.Request(
            url=f"{self.api_base_url}/groups?{query}",
            headers={"Authorization": self.api_token},
            method="GET",
        )
        payload = self._perform_request(http_request)
        groups = payload.get("list")
        if not isinstance(groups, list):
            return None
        for group in groups:
            if not isinstance(group, dict):
                continue
            candidate_name = _payload_str(group, "name")
            candidate_id = _payload_str(group, "id")
            if candidate_id and _normalize_group_name(candidate_name) == _normalize_group_name(group_name):
                return BallchasingReplayGroup(id=candidate_id, name=candidate_name)
        return None

    def _create_group(
            self,
            *,
            parent_group_id: str,
            group_name: str,
    ) -> BallchasingReplayGroup:
        body = json.dumps(
            {
                "name": group_name,
                "parent": parent_group_id,
                "player_identification": "by-id",
                "team_identification": "by-player-clusters",
            }
        ).encode("utf-8")
        http_request = request.Request(
            url=f"{self.api_base_url}/groups",
            data=body,
            headers={
                "Authorization": self.api_token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        payload = self._perform_request(http_request)
        group_id = _payload_str(payload, "id")
        if not group_id:
            raise BallchasingClientError(
                localize(I18N.errors.match_replays.ballchasing_invalid_response)
            )
        LOGGER.info(
            "Grupo Ballchasing creado parent_group_id=%s group_id=%s name=%s",
            parent_group_id,
            group_id,
            group_name,
        )
        return BallchasingReplayGroup(id=group_id, name=group_name)

    def _perform_request(
            self,
            http_request: request.Request,
            *,
            allow_duplicate_replay: bool = False,
    ) -> dict[str, Any]:
        for attempt in range(1, self.rate_limit_max_retries + 2):
            _throttle_request(self.min_request_interval_seconds)
            try:
                with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                    response_body = response.read().decode("utf-8")
            except error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace").strip()
                if exc.code == 429 and attempt <= self.rate_limit_max_retries:
                    retry_after_seconds = _retry_after_seconds(
                        exc,
                        default_seconds=self.rate_limit_retry_seconds,
                    )
                    LOGGER.warning(
                        "Ballchasing rate limit alcanzado method=%s url=%s attempt=%s/%s retry_after=%s details=%s",
                        http_request.get_method(),
                        http_request.full_url,
                        attempt,
                        self.rate_limit_max_retries + 1,
                        retry_after_seconds,
                        details or exc.reason,
                    )
                    time.sleep(retry_after_seconds)
                    continue
                if allow_duplicate_replay and exc.code == 409:
                    payload = self._parse_response_body(details)
                    _extract_replay_id(payload)
                    return payload

                raise BallchasingClientError(
                    localize(
                        I18N.errors.match_replays.ballchasing_request_failed,
                        details=details or exc.reason,
                    )
                ) from exc
            except error.URLError as exc:
                raise BallchasingClientError(
                    localize(
                        I18N.errors.match_replays.ballchasing_request_failed,
                        details=str(exc.reason),
                    )
                ) from exc

            return self._parse_response_body(response_body)

        raise BallchasingClientError(
            localize(
                I18N.errors.match_replays.ballchasing_request_failed,
                details="Too many requests",
            )
        )

    def _perform_empty_request(
            self,
            http_request: request.Request,
    ) -> None:
        for attempt in range(1, self.rate_limit_max_retries + 2):
            _throttle_request(self.min_request_interval_seconds)
            try:
                with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                    response.read()
            except error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace").strip()
                if exc.code == 429 and attempt <= self.rate_limit_max_retries:
                    retry_after_seconds = _retry_after_seconds(
                        exc,
                        default_seconds=self.rate_limit_retry_seconds,
                    )
                    LOGGER.warning(
                        "Ballchasing rate limit alcanzado method=%s url=%s attempt=%s/%s retry_after=%s details=%s",
                        http_request.get_method(),
                        http_request.full_url,
                        attempt,
                        self.rate_limit_max_retries + 1,
                        retry_after_seconds,
                        details or exc.reason,
                    )
                    time.sleep(retry_after_seconds)
                    continue
                raise BallchasingClientError(
                    localize(
                        I18N.errors.match_replays.ballchasing_request_failed,
                        details=details or exc.reason,
                    )
                ) from exc
            except error.URLError as exc:
                raise BallchasingClientError(
                    localize(
                        I18N.errors.match_replays.ballchasing_request_failed,
                        details=str(exc.reason),
                    )
                ) from exc
            return

    @staticmethod
    def _parse_response_body(
            response_body: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise BallchasingClientError(
                localize(I18N.errors.match_replays.ballchasing_invalid_response)
            ) from exc

        if not isinstance(payload, dict):
            raise BallchasingClientError(
                localize(I18N.errors.match_replays.ballchasing_invalid_response)
            )
        return payload


def _build_multipart_body(
        *,
        field_name: str,
        filename: str,
        content: bytes,
) -> tuple[bytes, str]:
    boundary = f"bigness-{int(time.time())}-{uuid.uuid4().hex}"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        "Content-Type: binary/octet-stream\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return header + content + footer, f"multipart/form-data; boundary={boundary}"


def _extract_replay_id(payload: dict[str, Any]) -> str:
    for key in ("id", "replay_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    location = payload.get("location")
    if isinstance(location, str) and location.strip():
        return location.rstrip("/").rsplit("/", maxsplit=1)[-1]

    raise BallchasingClientError(
        localize(I18N.errors.match_replays.ballchasing_invalid_response)
    )


def _parse_replay_payload(payload: dict[str, Any]) -> MatchReplayGame:
    replay_id = _payload_str(payload, "id")
    blue = _parse_team(payload.get("blue"), color="blue")
    orange = _parse_team(payload.get("orange"), color="orange")
    return MatchReplayGame(
        number=0,
        replay_id=replay_id,
        replay_url=f"https://ballchasing.com/replay/{replay_id}",
        blue=blue,
        orange=orange,
    )


def _parse_team(
        payload: Any,
        *,
        color: str,
) -> MatchReplayTeam:
    if not isinstance(payload, dict):
        raise BallchasingClientError(
            localize(I18N.errors.match_replays.ballchasing_invalid_response)
        )

    players_payload = payload.get("players")
    players: list[MatchReplayPlayer] = []
    if isinstance(players_payload, list):
        players = [
            _parse_player(player_payload)
            for player_payload in players_payload
            if isinstance(player_payload, dict)
        ]

    return MatchReplayTeam(
        color=color,
        name=_payload_str(payload, "name") or color.title(),
        goals=_payload_int(payload, "goals", default=_core_stat_int(payload, "goals", default=0)),
        players=tuple(players),
    )


def _parse_player(payload: dict[str, Any]) -> MatchReplayPlayer:
    player_id = payload.get("id")
    platform = ""
    platform_id = ""
    if isinstance(player_id, dict):
        platform = _payload_str(player_id, "platform")
        platform_id = _payload_str(player_id, "id")

    return MatchReplayPlayer(
        name=_payload_str(payload, "name"),
        platform=platform,
        platform_id=platform_id,
        score=_payload_or_core_stat_int(payload, "score"),
        goals=_payload_or_core_stat_int(payload, "goals"),
        assists=_payload_or_core_stat_int(payload, "assists"),
        saves=_payload_or_core_stat_int(payload, "saves"),
        shots=_payload_or_core_stat_int(payload, "shots"),
    )


def _has_processed_score(payload: dict[str, Any]) -> bool:
    blue = payload.get("blue")
    orange = payload.get("orange")
    if not isinstance(blue, dict) or not isinstance(orange, dict):
        return False
    return (
            _payload_int(blue, "goals", default=_core_stat_int(blue, "goals", default=-1)) >= 0
            and _payload_int(orange, "goals", default=_core_stat_int(orange, "goals", default=-1)) >= 0
    )


def _payload_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def _normalize_group_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _throttle_request(min_interval_seconds: float) -> None:
    if min_interval_seconds <= 0:
        return

    global _LAST_REQUEST_MONOTONIC
    with _REQUEST_THROTTLE_LOCK:
        now = time.monotonic()
        elapsed = now - _LAST_REQUEST_MONOTONIC
        if elapsed < min_interval_seconds:
            time.sleep(min_interval_seconds - elapsed)
        _LAST_REQUEST_MONOTONIC = time.monotonic()


def _retry_after_seconds(
        exc: error.HTTPError,
        *,
        default_seconds: float,
) -> float:
    retry_after = exc.headers.get("Retry-After")
    if retry_after is None:
        return default_seconds
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        return default_seconds


def _payload_int(
        payload: dict[str, Any],
        key: str,
        *,
        default: int,
) -> int:
    value = _optional_payload_int(payload, key)
    if value is None:
        return default
    return value


def _optional_payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _payload_or_core_stat_int(payload: dict[str, Any], key: str) -> int | None:
    value = _optional_payload_int(payload, key)
    if value is not None:
        return value
    return _optional_core_stat_int(payload, key)


def _core_stat_int(
        payload: dict[str, Any],
        key: str,
        *,
        default: int,
) -> int:
    value = _optional_core_stat_int(payload, key)
    if value is None:
        return default
    return value


def _optional_core_stat_int(payload: dict[str, Any], key: str) -> int | None:
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        return None
    core = stats.get("core")
    if not isinstance(core, dict):
        return None
    return _optional_payload_int(core, key)
