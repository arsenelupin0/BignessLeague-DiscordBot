from __future__ import annotations

TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER = "```"
TEAM_SIGNING_GUIDE_MIN_PLAYERS = 1
TEAM_SIGNING_GUIDE_MAX_PLAYERS = 6


def build_team_signing_guide_content(
        content: str,
        *,
        player_count: int,
) -> str:
    if not TEAM_SIGNING_GUIDE_MIN_PLAYERS <= player_count <= TEAM_SIGNING_GUIDE_MAX_PLAYERS:
        raise ValueError(
            "player_count debe estar entre "
            f"{TEAM_SIGNING_GUIDE_MIN_PLAYERS} y {TEAM_SIGNING_GUIDE_MAX_PLAYERS}."
        )

    rebuilt_parts: list[str] = []
    search_start_index = 0
    rebuilt_any_template = False

    while True:
        opening_marker_index = content.find(
            TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER,
            search_start_index,
        )
        if opening_marker_index < 0:
            rebuilt_parts.append(content[search_start_index:])
            break

        body_start_index = opening_marker_index + len(TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER)
        closing_marker_index = content.find(
            TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER,
            body_start_index,
        )
        if closing_marker_index < 0:
            rebuilt_parts.append(content[search_start_index:])
            break

        rebuilt_parts.append(content[search_start_index:body_start_index])
        code_block = content[body_start_index:closing_marker_index]
        rebuilt_code_block = _build_repeated_template_code_block(
            code_block,
            player_count=player_count,
        )
        rebuilt_parts.append(rebuilt_code_block)
        rebuilt_any_template = rebuilt_any_template or rebuilt_code_block != code_block
        search_start_index = closing_marker_index

    if not rebuilt_any_template:
        return content

    return "".join(rebuilt_parts)


def build_team_signing_raw_template_content(
        content: str,
        *,
        player_count: int,
) -> str:
    guide_content = build_team_signing_guide_content(
        content,
        player_count=player_count,
    )
    template_contents = _extract_code_blocks(guide_content)
    if not template_contents:
        return guide_content.strip()

    return "\n\n".join(
        TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER
        + "\n"
        + template_content.strip()
        + "\n"
        + TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER
        for template_content in template_contents
    )


def _build_repeated_template_code_block(
        code_block: str,
        *,
        player_count: int,
) -> str:
    leading_newline = "\n" if code_block.startswith("\n") else ""
    trailing_newline = "\n" if code_block.endswith("\n") else ""
    template_lines = code_block.strip("\n").splitlines()
    player_block_start_index = _find_repeatable_template_block_start(template_lines)
    if player_block_start_index is None:
        return code_block

    metadata_lines = _strip_trailing_blank_lines(
        template_lines[:player_block_start_index]
    )
    repeatable_block_lines = _strip_trailing_blank_lines(
        template_lines[player_block_start_index:]
    )
    repeated_template_lines = [
        *metadata_lines,
        "",
        *_repeat_template_block(
            repeatable_block_lines,
            player_count=player_count,
        ),
    ]
    rebuilt_code_block = "\n".join(repeated_template_lines)
    return leading_newline + rebuilt_code_block + trailing_newline


def _extract_code_blocks(content: str) -> tuple[str, ...]:
    code_blocks: list[str] = []
    search_start_index = 0

    while True:
        opening_marker_index = content.find(
            TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER,
            search_start_index,
        )
        if opening_marker_index < 0:
            break

        body_start_index = opening_marker_index + len(TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER)
        closing_marker_index = content.find(
            TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER,
            body_start_index,
        )
        if closing_marker_index < 0:
            break

        code_blocks.append(content[body_start_index:closing_marker_index])
        search_start_index = closing_marker_index + len(
            TEAM_SIGNING_GUIDE_TEMPLATE_BLOCK_MARKER
        )

    return tuple(code_blocks)


def _find_repeatable_template_block_start(template_lines: list[str]) -> int | None:
    for line_index, line in enumerate(template_lines):
        normalized_line = line.strip().casefold()
        if normalized_line.startswith(("jugador:", "player:", "rol:", "role:")):
            return line_index

    return None


def _repeat_template_block(
        block_lines: list[str],
        *,
        player_count: int,
) -> list[str]:
    repeated_lines: list[str] = []
    for player_index in range(player_count):
        if player_index > 0:
            repeated_lines.append("")
        repeated_lines.extend(block_lines)

    return repeated_lines


def _strip_trailing_blank_lines(lines: list[str]) -> list[str]:
    stripped_lines = list(lines)
    while stripped_lines and not stripped_lines[-1].strip():
        stripped_lines.pop()

    return stripped_lines
