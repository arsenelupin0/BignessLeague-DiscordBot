#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.
"""Name-based roster hints. These candidates never verify an account."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import groupby
from typing import Iterable

from bigness_league_bot.application.services.match_replay_identity import normalize_replay_name
from bigness_league_bot.application.services.match_replay_models import MatchReplayRosterPlayer

MIN_NAME_SIMILARITY = 0.84
MIN_CANDIDATE_MARGIN = 0.08


@dataclass(frozen=True, slots=True)
class ReplayRosterNameCandidate:
    player: MatchReplayRosterPlayer | None = None
    ambiguous: bool = False


def find_replay_roster_name_candidate(
        replay_name: str,
        roster_players: Iterable[MatchReplayRosterPlayer],
) -> ReplayRosterNameCandidate:
    name = normalize_replay_name(replay_name)
    if not 4 <= len(name) <= 128:
        return ReplayRosterNameCandidate()
    scored = sorted(
        ((max(_name_similarity(name, entry.player_name), _name_similarity(name, entry.epic_name)), entry)
         for entry in roster_players),
        key=lambda item: item[0], reverse=True,
    )
    if not scored or scored[0][0] < MIN_NAME_SIMILARITY:
        return ReplayRosterNameCandidate()
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MIN_CANDIDATE_MARGIN:
        return ReplayRosterNameCandidate(ambiguous=True)
    return ReplayRosterNameCandidate(player=scored[0][1])


def _name_similarity(name: str, reference: str) -> float:
    candidate = normalize_replay_name(reference)
    if not 4 <= len(candidate) <= 128:
        return 0.0
    # This score compares text, not the probability of sharing an identity.
    score = min(SequenceMatcher(None, name, candidate, autojunk=False).ratio(),
                SequenceMatcher(None, candidate, name, autojunk=False).ratio())
    collapsed = "".join(character for character, _ in groupby(name))
    other_collapsed = "".join(character for character, _ in groupby(candidate))
    if len(collapsed) >= 4 and collapsed == other_collapsed:
        score = max(score, 0.94)
    return score
