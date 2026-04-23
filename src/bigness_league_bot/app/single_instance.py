from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TextIO

from bigness_league_bot.core.settings import Settings

if os.name == "nt":
    import msvcrt
else:
    import fcntl

LOGGER = logging.getLogger(__name__)


class SingleInstanceLockError(RuntimeError):
    """Raised when another live bot instance already holds the process lock."""


class SingleInstanceGuard(AbstractContextManager["SingleInstanceGuard"]):
    def __init__(self, lock_file: Path, *, metadata: str) -> None:
        self._lock_file = lock_file
        self._metadata = metadata
        self._handle: TextIO | None = None

    def __enter__(self) -> "SingleInstanceGuard":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        self.release()

    def acquire(self) -> None:
        if self._handle is not None:
            return

        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_file.open("a+", encoding="utf-8")
        _prepare_lock_region(handle)

        try:
            _lock_handle(handle)
        except OSError as exc:
            owner_summary = _read_lock_owner_summary(handle)
            handle.close()
            details = f" Proceso activo: {owner_summary}." if owner_summary else ""
            raise SingleInstanceLockError(
                "Ya hay otra instancia del bot activa para este token."
                f"{details} Lock file: {self._lock_file}."
            ) from exc

        handle.seek(0)
        handle.write(self._metadata)
        handle.truncate()
        handle.flush()
        _flush_to_disk(handle)
        self._handle = handle
        LOGGER.info("INSTANCE_LOCK_ACQUIRED path=%s", self._lock_file)

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return

        try:
            _unlock_handle(handle)
        finally:
            handle.close()
            self._handle = None
            LOGGER.info("INSTANCE_LOCK_RELEASED path=%s", self._lock_file)


def create_single_instance_guard(settings: Settings) -> SingleInstanceGuard:
    token_fingerprint = hashlib.sha256(settings.token.encode("utf-8")).hexdigest()[:16]
    lock_file = settings.log_dir.parent / "locks" / f"bigness-league-bot-{token_fingerprint}.lock"
    metadata = json.dumps(
        {
            "pid": os.getpid(),
            "environment": settings.environment,
            "guild_id": settings.guild_id,
            "cwd": str(Path.cwd()),
        },
        ensure_ascii=True,
    )
    return SingleInstanceGuard(lock_file, metadata=metadata)


def _prepare_lock_region(handle: TextIO) -> None:
    if os.name != "nt":
        return

    handle.seek(0, os.SEEK_END)
    if handle.tell() > 0:
        handle.seek(0)
        return

    handle.write(" ")
    handle.flush()
    _flush_to_disk(handle)
    handle.seek(0)


def _lock_handle(handle: TextIO) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        handle.seek(0)
        return

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: TextIO) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.seek(0)
        return

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _flush_to_disk(handle: TextIO) -> None:
    try:
        os.fsync(handle.fileno())
    except OSError:
        return


def _read_lock_owner_summary(handle: TextIO) -> str | None:
    try:
        handle.seek(0)
        raw_value = handle.read().strip()
    except OSError:
        return None

    if not raw_value:
        return None

    try:
        metadata = json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value

    details: list[str] = []
    pid = metadata.get("pid")
    if isinstance(pid, int):
        details.append(f"pid={pid}")

    environment = metadata.get("environment")
    if isinstance(environment, str) and environment:
        details.append(f"env={environment}")

    guild_id = metadata.get("guild_id")
    if isinstance(guild_id, int):
        details.append(f"guild={guild_id}")

    cwd = metadata.get("cwd")
    if isinstance(cwd, str) and cwd:
        details.append(f"cwd={cwd}")

    return " ".join(details) or raw_value
