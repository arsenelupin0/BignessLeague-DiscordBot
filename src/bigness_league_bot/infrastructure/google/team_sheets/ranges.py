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


def _build_a1_range(
        worksheet_title: str,
        start_row: int,
        start_column: int,
        row_count: int,
        column_count: int,
) -> str:
    start_cell = f"{_column_to_letter(start_column)}{start_row + 1}"
    end_cell = (
        f"{_column_to_letter(start_column + column_count - 1)}"
        f"{start_row + row_count}"
    )
    escaped_title = worksheet_title.replace("'", "''")
    return f"'{escaped_title}'!{start_cell}:{end_cell}"


def _column_to_letter(column_index: int) -> str:
    value = column_index + 1
    letters: list[str] = []
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("A") + remainder))

    return "".join(reversed(letters))
