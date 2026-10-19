"""Prepare the pinned parser shipped with the repository, entirely offline."""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import tarfile
import threading
import uuid
import zipfile
from importlib.resources import files
from pathlib import Path

VERSION = "0.11.8"
BOXCARS_VERSION = "0.13.0"
ASSETS = {
    ("Windows", "x86_64"): ("x86_64-pc-windows-msvc.zip",
                            "bc652d48b382f25b7ff1da65942b6800366501ed1c2eb1d440058bb1821a7869"),
    ("Linux", "x86_64"): ("x86_64-unknown-linux-musl.tar.gz",
                          "c78b674728de915fa1a76ea7fec16d57df7f9371fbbc1062f4f50b44999f530f"),
    ("Darwin", "x86_64"): ("x86_64-apple-darwin.tar.gz",
                           "2940f4e54c80967c8d7d2d2d8775a23cc89408a05c007bb9986fbd4b720f63fd"),
    ("Darwin", "aarch64"): ("aarch64-apple-darwin.tar.gz",
                            "1408f9dc0f3741e7755f8e19f65b8d75e039394d8b7fa1f8912c6e292acf4723"),
}
LICENSE_SHA256 = "91276db973f25602d1aa43491f59cbc84cb88e6f151e1d0cc82a755563ce0195"
_INSTALL_LOCK = threading.Lock()


class ReplayRuntimeError(Exception):
    pass


def executable_name() -> str:
    return "rrrocket.exe" if platform.system() == "Windows" else "rrrocket"


def host_asset() -> tuple[str, str]:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    selected = ASSETS.get((platform.system(), machine))
    if selected is None:
        raise ReplayRuntimeError(f"unsupported_platform:{platform.system()}/{machine}")
    return selected


def executable_from_archive(content: bytes, *, windows: bool) -> bytes:
    name = "rrrocket.exe" if windows else "rrrocket"
    if windows:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            matches = [entry for entry in archive.infolist()
                       if Path(entry.filename).name == name and not entry.is_dir()]
            if len(matches) != 1 or matches[0].file_size > 16 * 1024 * 1024:
                raise ReplayRuntimeError("invalid_archive")
            return archive.read(matches[0])
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        matches = [entry for entry in archive.getmembers() if Path(entry.name).name == name and entry.isfile()]
        if len(matches) != 1 or matches[0].size > 16 * 1024 * 1024:
            raise ReplayRuntimeError("invalid_archive")
        source = archive.extractfile(matches[0])
        assert source is not None
        return source.read()


def _read_bundled(name: str, digest: str) -> bytes:
    try:
        data = files("bigness_league_bot.infrastructure.replays").joinpath("vendor", name).read_bytes()
    except OSError as exc:
        raise ReplayRuntimeError(f"missing_bundle:{name}") from exc
    if hashlib.sha256(data).hexdigest() != digest:
        raise ReplayRuntimeError(f"bundle_checksum:{name}")
    return data


def _current(target: Path, digest: str) -> bool:
    try:
        manifest = json.loads((target.parent / "manifest.json").read_text(encoding="utf-8"))
        return (isinstance(manifest, dict) and manifest.get("version") == VERSION
                and manifest.get("archive_sha256") == digest
                and manifest.get("executable_sha256") == hashlib.sha256(target.read_bytes()).hexdigest()
                and (os.name == "nt" or os.access(target, os.X_OK)))
    except (OSError, ValueError):
        return False


def _atomic_write(path: Path, content: bytes, *, executable: bool = False) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        if executable and os.name != "nt":
            temporary.chmod(0o755)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_bundled_runtime(target: Path, *, force: bool = False) -> Path:
    suffix, digest = host_asset()
    target = target.resolve()
    with _INSTALL_LOCK:
        if not force and _current(target, digest):
            return target
        asset = f"rrrocket-{VERSION}-{suffix}"
        content = _read_bundled(asset, digest)
        license_content = _read_bundled("LICENSE.txt", LICENSE_SHA256)
        try:
            binary = executable_from_archive(content, windows=platform.system() == "Windows")
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, binary, executable=True)
            _atomic_write(target.parent / "LICENSE.txt", license_content)
            manifest = {"version": VERSION, "boxcars_version": BOXCARS_VERSION,
                        "source": f"https://github.com/nickbabcock/rrrocket/releases/download/v{VERSION}/{asset}",
                        "archive_sha256": digest, "executable_sha256": hashlib.sha256(binary).hexdigest()}
            _atomic_write(target.parent / "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
            raise ReplayRuntimeError(f"prepare_failed:{type(exc).__name__}:{exc}") from exc
    return target
