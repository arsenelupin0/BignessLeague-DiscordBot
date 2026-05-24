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

import re
from dataclasses import dataclass

from bigness_league_bot.application.services.channel_closure import (
    KEYCAP_SUFFIX,
    MATCH_CHANNEL_J_PREFIX,
    MATCH_CHANNEL_P_PREFIX,
    MATCH_CHANNEL_STATUS_PATTERN,
    MATCH_CHANNEL_STATUS_SEPARATOR,
)
from bigness_league_bot.application.services.match_replays import MatchReplayDivision

MATCHUP_SEPARATOR = "\U0001F19A"
KEYCAP_DIGIT_PATTERN = rf"[0-9]{re.escape(KEYCAP_SUFFIX)}"

MATCH_CHANNEL_LEGACY_REFERENCE_PATTERN = re.compile(
    rf"^j(?P<jornada>[1-9][0-9]?)-partido-(?P<partido>[1-9][0-9]?)"
    rf"(?:{re.escape(MATCH_CHANNEL_STATUS_SEPARATOR)}{MATCH_CHANNEL_STATUS_PATTERN})?$"
)
MATCH_CHANNEL_EMOJI_REFERENCE_PATTERN = re.compile(
    rf"^{re.escape(MATCH_CHANNEL_J_PREFIX)}(?P<jornada>(?:{KEYCAP_DIGIT_PATTERN}){{1,2}})"
    rf"{re.escape(MATCH_CHANNEL_P_PREFIX)}(?P<partido>(?:{KEYCAP_DIGIT_PATTERN}){{1,2}})"
    rf"{re.escape(MATCH_CHANNEL_STATUS_SEPARATOR)}{MATCH_CHANNEL_STATUS_PATTERN}$"
)


@dataclass(frozen=True, slots=True)
class MatchChannelReference:
    matchday: int
    match_number: int


@dataclass(frozen=True, slots=True)
class MatchReplayGroupPath:
    division_group_name: str
    matchday_group_name: str
    matchup_group_name: str

    @property
    def names(self) -> tuple[str, str, str]:
        return (
            self.division_group_name,
            self.matchday_group_name,
            self.matchup_group_name,
        )

    @property
    def label(self) -> str:
        return " -> ".join(self.names)


def parse_match_channel_reference(channel_name: str) -> MatchChannelReference | None:
    normalized_name = channel_name.strip()
    legacy_match = MATCH_CHANNEL_LEGACY_REFERENCE_PATTERN.fullmatch(normalized_name)
    if legacy_match is not None:
        return MatchChannelReference(
            matchday=int(legacy_match.group("jornada")),
            match_number=int(legacy_match.group("partido")),
        )

    emoji_match = MATCH_CHANNEL_EMOJI_REFERENCE_PATTERN.fullmatch(normalized_name)
    if emoji_match is None:
        return None

    return MatchChannelReference(
        matchday=_parse_keycap_number(emoji_match.group("jornada")),
        match_number=_parse_keycap_number(emoji_match.group("partido")),
    )


def build_match_replay_group_path(
        *,
        division: MatchReplayDivision,
        matchday: int,
        team_one_name: str,
        team_two_name: str,
) -> MatchReplayGroupPath:
    return MatchReplayGroupPath(
        division_group_name=_division_group_name(division),
        matchday_group_name=f"Jornada {matchday}",
        matchup_group_name=build_matchup_name(
            team_one_name=team_one_name,
            team_two_name=team_two_name,
        ),
    )


def build_matchup_name(
        *,
        team_one_name: str,
        team_two_name: str,
) -> str:
    return f"{team_one_name.strip()} {MATCHUP_SEPARATOR} {team_two_name.strip()}"


def build_match_replay_title(
        *,
        matchday: int,
        game_number: int,
        team_one_name: str,
        team_two_name: str,
) -> str:
    return (
        f"{build_matchup_name(team_one_name=team_one_name, team_two_name=team_two_name)} "
        f"- Jornada {matchday} | Match {game_number}"
    )


def _division_group_name(division: MatchReplayDivision) -> str:
    if division is MatchReplayDivision.GOLD:
        return "GOLD DIVISION"
    return "SILVER DIVISION"


def _parse_keycap_number(value: str) -> int:
    digits = "".join(character for character in value if character.isdigit())
    return int(digits)
