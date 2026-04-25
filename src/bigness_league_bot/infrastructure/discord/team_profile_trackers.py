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

import html
from urllib.parse import unquote, urlsplit, urlunsplit

import discord

from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.infrastructure.discord.team_profile_layout import sanitize_text
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def build_team_profile_tracker_markdown(
        *,
        team_profile: TeamProfile,
        localizer: LocalizationService,
        locale: str | discord.Locale | None,
) -> str:
    title = localizer.translate(
        I18N.messages.team_profile.trackers.title,
        locale=locale,
    )
    empty_message = localizer.translate(
        I18N.messages.team_profile.trackers.empty,
        locale=locale,
    )
    entries: list[str] = []
    for player in team_profile.players:
        destination_url = _normalize_tracker_destination_url(player.tracker_url)
        if destination_url is None:
            continue

        display_url = _display_tracker_value(
            player.tracker_url,
            localizer.translate(
                I18N.messages.team_profile.trackers.missing_value,
                locale=locale,
            ),
        )
        entries.append(
            localizer.translate(
                I18N.messages.team_profile.trackers.entry,
                locale=locale,
                emoji=_position_emoji(player.position),
                display_url=_escape_markdown_link_label(display_url),
                destination_url=destination_url,
            )
        )

    if not entries:
        return f"{title}\n{empty_message}"

    return "\n".join([title, *entries])


def _display_tracker_value(url: str | None, missing_value: str) -> str:
    destination_url = _normalize_tracker_destination_url(url)
    if destination_url is None:
        return missing_value

    normalized_url = destination_url
    for prefix in ("https://", "http://"):
        if normalized_url.startswith(prefix):
            normalized_url = normalized_url[len(prefix):]
            break

    if "/" in normalized_url:
        base_path, tracker_identifier = normalized_url.rsplit("/", 1)
        normalized_url = (
            f"{base_path}/"
            f"{_decode_tracker_identifier(tracker_identifier)}"
        )

    return normalized_url or missing_value


def _decode_tracker_identifier(value: str) -> str:
    decoded_value = html.unescape(unquote(value))
    return decoded_value.replace("/", "%2F")


def _normalize_tracker_destination_url(url: str | None) -> str | None:
    if not url:
        return None

    normalized_url = sanitize_text(url)
    if not normalized_url.startswith(("https://", "http://")):
        normalized_url = f"https://{normalized_url}"

    split_url = urlsplit(normalized_url)
    path_segments = [segment for segment in split_url.path.split("/") if segment]
    if not path_segments:
        return None

    canonical_segments = path_segments
    if (
            len(path_segments) >= 4
            and path_segments[0].casefold() == "rocket-league"
            and path_segments[1].casefold() == "profile"
    ):
        canonical_segments = path_segments[:4]
    elif len(path_segments) > 1:
        canonical_segments = path_segments[:-1]

    canonical_path = "/" + "/".join(canonical_segments)
    canonical_url = urlunsplit(
        (
            split_url.scheme or "https",
            split_url.netloc,
            canonical_path,
            "",
            "",
        )
    ).rstrip("/")

    return canonical_url or None


def _position_emoji(position: int) -> str:
    mapping = {
        1: ":one:",
        2: ":two:",
        3: ":three:",
        4: ":four:",
        5: ":five:",
        6: ":six:",
    }
    return mapping.get(position, f"`{position}`")


def _escape_markdown_link_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
