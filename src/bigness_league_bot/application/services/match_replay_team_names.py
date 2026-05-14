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

TEAM_NAME_IGNORED_TOKENS = frozenset(
    {
        "academy",
        "club",
        "esport",
        "esports",
        "fc",
        "gaming",
        "rl",
        "team",
    }
)
TEAM_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def normalize_match_replay_team_name(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def match_replay_team_names_match(candidate: str, expected: str) -> bool:
    if candidate == expected:
        return True

    if candidate and expected and (candidate in expected or expected in candidate):
        return True

    candidate_tokens = set(match_replay_team_identity_tokens(candidate))
    expected_tokens = set(match_replay_team_identity_tokens(expected))
    if not candidate_tokens or not expected_tokens:
        return False

    return candidate_tokens <= expected_tokens or expected_tokens <= candidate_tokens


def match_replay_team_identity_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in TEAM_TOKEN_PATTERN.findall(normalize_match_replay_team_name(value))
        if token not in TEAM_NAME_IGNORED_TOKENS
    )
