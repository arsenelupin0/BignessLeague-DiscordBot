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
    FINAL_FOUR_FINAL_MARKER,
    FINAL_FOUR_FINAL_PREFIX,
    FINAL_FOUR_SEMIFINAL_PREFIX,
    KEYCAP_SUFFIX,
    MATCH_CHANNEL_J_PREFIX,
    MATCH_CHANNEL_P_PREFIX,
    MATCH_CHANNEL_STATUS_PATTERN,
    MATCH_CHANNEL_STATUS_SEPARATOR,
    PROMOTION_RELEGATION_MARKER,
    PROMOTION_RELEGATION_PREFIX,
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
FINAL_FOUR_SEMIFINAL_REFERENCE_PATTERN = re.compile(
    rf"^{re.escape(FINAL_FOUR_SEMIFINAL_PREFIX)}"
    rf"(?P<semifinal>[12]{re.escape(KEYCAP_SUFFIX)})"
    rf"{re.escape(MATCH_CHANNEL_STATUS_SEPARATOR)}{MATCH_CHANNEL_STATUS_PATTERN}$"
)
FINAL_FOUR_FINAL_REFERENCE_PATTERN = re.compile(
    rf"^{re.escape(FINAL_FOUR_FINAL_PREFIX)}{re.escape(FINAL_FOUR_FINAL_MARKER)}"
    rf"{re.escape(MATCH_CHANNEL_STATUS_SEPARATOR)}{MATCH_CHANNEL_STATUS_PATTERN}$"
)
PROMOTION_RELEGATION_REFERENCE_PATTERN = re.compile(
    rf"^{re.escape(PROMOTION_RELEGATION_PREFIX)}{re.escape(PROMOTION_RELEGATION_MARKER)}"
    rf"{re.escape(MATCH_CHANNEL_STATUS_SEPARATOR)}{MATCH_CHANNEL_STATUS_PATTERN}$"
)


@dataclass(frozen=True, slots=True)
class MatchChannelReference:
    matchday: int
    match_number: int


@dataclass(frozen=True, slots=True)
class FinalFourMatchReference:
    round_name: str
    matchday: int
    match_number: int

    @property
    def label(self) -> str:
        return self.round_name


@dataclass(frozen=True, slots=True)
class PromotionRelegationMatchReference:
    round_name: str = "Ascenso/Descenso"
    matchday: int = 10
    match_number: int = 1

    @property
    def label(self) -> str:
        return self.round_name


@dataclass(frozen=True, slots=True)
class MatchReplayGroupPath:
    names: tuple[str, ...]

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


def parse_final_four_channel_reference(channel_name: str) -> FinalFourMatchReference | None:
    normalized_name = channel_name.strip()
    semifinal_match = FINAL_FOUR_SEMIFINAL_REFERENCE_PATTERN.fullmatch(normalized_name)
    if semifinal_match is not None:
        semifinal_number = _parse_keycap_number(semifinal_match.group("semifinal"))
        return FinalFourMatchReference(
            round_name=f"Semifinal {semifinal_number}",
            matchday=8,
            match_number=semifinal_number,
        )

    if FINAL_FOUR_FINAL_REFERENCE_PATTERN.fullmatch(normalized_name) is not None:
        return FinalFourMatchReference(
            round_name="Final",
            matchday=9,
            match_number=1,
        )

    return None


def parse_promotion_relegation_channel_reference(
        channel_name: str,
) -> PromotionRelegationMatchReference | None:
    normalized_name = channel_name.strip()
    if PROMOTION_RELEGATION_REFERENCE_PATTERN.fullmatch(normalized_name) is None:
        return None

    return PromotionRelegationMatchReference()


def build_match_replay_group_path(
        *,
        division: MatchReplayDivision,
        matchday: int,
        team_one_name: str,
        team_two_name: str,
) -> MatchReplayGroupPath:
    return MatchReplayGroupPath(
        names=(
            _division_group_name(division),
            f"Jornada {matchday}",
            build_matchup_name(
                team_one_name=team_one_name,
                team_two_name=team_two_name,
            ),
        ),
    )


def build_final_four_replay_group_path(
        *,
        round_name: str,
) -> MatchReplayGroupPath:
    return MatchReplayGroupPath(names=("FINAL FOUR", round_name))


def build_promotion_relegation_replay_group_path(
        *,
        team_one_name: str,
        team_two_name: str,
) -> MatchReplayGroupPath:
    return MatchReplayGroupPath(
        names=(
            "ASCENSO / DESCENSO",
            build_matchup_name(
                team_one_name=team_one_name,
                team_two_name=team_two_name,
            ),
        )
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


def build_final_four_replay_title(
        *,
        round_name: str,
        game_number: int,
        team_one_name: str,
        team_two_name: str,
) -> str:
    return (
        f"{build_matchup_name(team_one_name=team_one_name, team_two_name=team_two_name)} "
        f"- Final Four | {round_name} | Match {game_number}"
    )


def build_promotion_relegation_replay_title(
        *,
        game_number: int,
        team_one_name: str,
        team_two_name: str,
) -> str:
    return (
        f"{build_matchup_name(team_one_name=team_one_name, team_two_name=team_two_name)} "
        f"- Ascenso/Descenso | Match {game_number}"
    )


def _division_group_name(division: MatchReplayDivision) -> str:
    if division is MatchReplayDivision.GOLD:
        return "GOLD DIVISION"
    return "SILVER DIVISION"


def _parse_keycap_number(value: str) -> int:
    digits = "".join(character for character in value if character.isdigit())
    return int(digits)
