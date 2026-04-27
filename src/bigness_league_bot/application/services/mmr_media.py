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

from dataclasses import dataclass

MMR_VALUE_COUNT = 3


@dataclass(frozen=True, slots=True)
class MmrMediaResult:
    average: int
    limit: int

    @property
    def is_eligible(self) -> bool:
        return self.average <= self.limit


def calculate_mmr_media(
        first_mmr: int,
        second_mmr: int,
        third_mmr: int,
        *,
        limit: int,
) -> MmrMediaResult:
    average = (first_mmr + second_mmr + third_mmr) // MMR_VALUE_COUNT
    return MmrMediaResult(
        average=average,
        limit=limit,
    )
