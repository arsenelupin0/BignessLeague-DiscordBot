from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from bigness_league_bot.application.services.team_logo import normalize_team_logo_url
from bigness_league_bot.core.settings import PROJECT_ROOT

LOGGER = logging.getLogger("bigness_league_bot.activity")
TEAM_LOGO_CACHE_DIRECTORY = PROJECT_ROOT / "aa_var" / "team_logos"
MAX_LOGO_BYTES = 4 * 1024 * 1024
MAX_LOGO_PIXELS = 16_000_000
LOGO_SIZE = 256
LOGO_TIMEOUT_SECONDS = 8
CACHE_REFRESH_SECONDS = 3600
SOURCE_METADATA_KEY = "bigness_logo_source"
_CACHE_LOCKS = tuple(Lock() for _ in range(64))


class TeamLogoLoadError(Exception):
    """A remote logo could not be downloaded or decoded as an image."""


@dataclass(frozen=True, slots=True)
class CachedTeamLogo:
    content: bytes
    modified_at: float
    source_key: str | None


async def load_team_logo_png_async(url: str | None, *, team_key: str) -> bytes:
    # Waiting for an executor worker or the team lock is not a download failure.
    # The HTTP request applies its own timeout once the worker can start it.
    return await asyncio.to_thread(load_team_logo_png, url, team_key=team_key)


def load_team_logo_png(
        url: str | None, *, team_key: str, cache_directory: Path = TEAM_LOGO_CACHE_DIRECTORY,
) -> bytes:
    if not team_key.strip():
        raise TeamLogoLoadError("invalid_team_key")
    key = hashlib.sha256(team_key.encode("utf-8")).hexdigest()
    cache_path = cache_directory / f"team-{key}.png"
    # Downloads for the same team are serialized so that a slow refresh cannot
    # overwrite a later replacement. Locks are bounded and shared by workers.
    with _CACHE_LOCKS[int(key, 16) % len(_CACHE_LOCKS)]:
        try:
            url = _validate_logo_url(url)
        except TeamLogoLoadError:
            _discard_cached_logo(cache_path, _read_cached_logo(cache_path))
            raise
        source_key = hashlib.sha256(_cache_identity(url).encode("utf-8")).hexdigest()
        return _load_team_logo_png(url, cache_path, source_key)


def _validate_logo_url(url: str | None) -> str:
    if not url or not url.strip():
        raise TeamLogoLoadError("missing_link")
    try:
        url = normalize_team_logo_url(url)
    except ValueError as exc:
        raise TeamLogoLoadError("invalid_url") from exc
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise TeamLogoLoadError("invalid_url")
    return url


def _load_team_logo_png(url: str, cache_path: Path, source_key: str) -> bytes:
    cached = _read_cached_logo(cache_path)
    matching_cache = cached is not None and cached.source_key == source_key
    if matching_cache and time.time() - cached.modified_at < CACHE_REFRESH_SECONDS:
        LOGGER.info("TEAM_LOGO_CACHE_HIT asset=%s source=%s", cache_path.stem, source_key[:12])
        return cached.content
    if not matching_cache:
        # A new source invalidates the previous image, including on failure.
        _discard_cached_logo(cache_path, cached)
    # Earlier releases stored a PNG per URL. Migrate only the exact source
    # requested; unrelated files cannot safely be assigned to this team.
    legacy_path = cache_path.parent / f"{source_key}.png"
    legacy = _read_cached_logo(legacy_path) if not matching_cache else None
    if legacy is not None and time.time() - legacy.modified_at < CACHE_REFRESH_SECONDS:
        if _write_cached_logo(cache_path, legacy.content, source_key):
            _remove_cached_logo(legacy_path)
        return legacy.content
    try:
        source = urlsplit(url)
        LOGGER.info("TEAM_LOGO_DOWNLOAD asset=%s source=%s host=%s path=%s",
                    cache_path.stem, source_key[:12], source.hostname, source.path)
        content = _download_logo_png(url)
    except TeamLogoLoadError:
        _discard_cached_logo(cache_path, cached)
        _remove_cached_logo(legacy_path)
        raise
    if _write_cached_logo(cache_path, content, source_key):
        _remove_cached_logo(legacy_path)
    else:
        _discard_cached_logo(cache_path, cached)
    return content


def _cache_identity(url: str) -> str:
    parsed = urlsplit(url)
    # Only the cache key loses expiring signatures. The HTTP request retains
    # the complete URL supplied by Sheets, including backend and signature.
    if parsed.hostname in ("cdn.discordapp.com", "media.discordapp.net") and parsed.path.startswith("/attachments/"):
        query = urlencode([(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                           if key not in {"ex", "is", "hm"}])
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
    return url


def _download_logo_png(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "BignessLeagueBot/1.0"})
    try:
        with urlopen(request, timeout=LOGO_TIMEOUT_SECONDS) as response:
            content = response.read(MAX_LOGO_BYTES + 1)
    except HTTPError as exc:
        raise TeamLogoLoadError(f"http_{exc.code}") from exc
    except (OSError, TimeoutError, URLError, ValueError) as exc:
        raise TeamLogoLoadError("download_failed") from exc
    return _normalize_logo_png(content)


def _normalize_logo_png(content: bytes) -> bytes:
    if not content or len(content) > MAX_LOGO_BYTES:
        raise TeamLogoLoadError("invalid_size")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise TeamLogoLoadError("image_dependency_unavailable") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.width * image.height > MAX_LOGO_PIXELS:
                    raise TeamLogoLoadError("invalid_dimensions")
                image.thumbnail((LOGO_SIZE, LOGO_SIZE))
                logo = image.convert("RGBA")
                output = BytesIO()
                logo.save(output, format="PNG")
                return output.getvalue()
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise TeamLogoLoadError("invalid_image") from exc


def _read_cached_logo(path: Path) -> CachedTeamLogo | None:
    try:
        with path.open("rb") as file:
            content = file.read(MAX_LOGO_BYTES + 1)
        normalized = _normalize_logo_png(content)
        from PIL import Image
        with Image.open(BytesIO(content)) as image:
            source_key = image.info.get(SOURCE_METADATA_KEY)
        return CachedTeamLogo(normalized, path.stat().st_mtime, source_key)
    except FileNotFoundError:
        return None
    except (OSError, TeamLogoLoadError):
        LOGGER.warning("TEAM_LOGO_CACHE_READ_FAILED asset=%s", path.stem)
        return None


def _write_cached_logo(path: Path, content: bytes, source_key: str) -> bool:
    temporary_path = path.with_name(f".{path.stem}-{uuid4().hex}.tmp")
    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
        metadata = PngInfo()
        metadata.add_text(SOURCE_METADATA_KEY, source_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(BytesIO(content)) as image:
            image.save(temporary_path, format="PNG", pnginfo=metadata)
        temporary_path.replace(path)
        return True
    except OSError:
        LOGGER.warning("TEAM_LOGO_CACHE_WRITE_FAILED asset=%s", path.stem)
        return False
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("TEAM_LOGO_CACHE_CLEANUP_FAILED asset=%s", path.stem)


def _discard_cached_logo(path: Path, cached: CachedTeamLogo | None) -> None:
    _remove_cached_logo(path)
    # The source stamp contains a SHA-256, never an arbitrary file path.
    source_key = cached.source_key if cached is not None else None
    if isinstance(source_key, str) and len(source_key) == 64 and all(c in "0123456789abcdef" for c in source_key):
        _remove_cached_logo(path.parent / f"{source_key}.png")


def _remove_cached_logo(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("TEAM_LOGO_CACHE_DELETE_FAILED asset=%s", path.stem)
