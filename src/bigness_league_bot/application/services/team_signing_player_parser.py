from __future__ import annotations

import unicodedata

from bigness_league_bot.application.services.team_signing_models import (
    MAX_TEAM_SIGNING_PLAYERS,
    MIN_TEAM_SIGNING_PLAYERS,
    TeamSigningBatch,
    TeamSigningParseError,
    TeamSigningPlayer,
    _parse_mmr_sort_value,
    sort_team_signing_players,
)
from bigness_league_bot.application.services.team_signing_template import (
    _contains_non_empty_lines,
    _extract_message_metadata_and_body,
    _label_for_field,
    _looks_like_labelled_format,
    _split_labelled_blocks,
    _unwrap_discord_code_block,
)

REQUIRED_PLAYER_FIELDS = (
    "position",
    "player_name",
    "tracker_url",
    "discord_name",
    "epic_name",
    "rocket_name",
    "mmr",
)
LABELLED_PLAYER_FIELD_KEYS = {
    "jugador": "player_name",
    "tracker": "tracker_url",
    "discord": "discord_name",
    "epic name": "epic_name",
    "rocket in-game name": "rocket_name",
    "mmr": "mmr",
}
LABELLED_PLAYER_FIELD_ORDER = tuple(LABELLED_PLAYER_FIELD_KEYS.values())


def parse_team_signing_message(content: str) -> TeamSigningBatch:
    content = _unwrap_discord_code_block(content)
    content_lines = content.splitlines()
    metadata, player_lines, player_start_line = _extract_message_metadata_and_body(
        content_lines
    )

    division_name = metadata.get("division_name", "")
    team_name = metadata.get("team_name", "")
    team_logo_url = metadata.get("team_logo_url") or None
    if not division_name:
        raise TeamSigningParseError("Falta la cabecera `División:` en el mensaje enlazado.")
    if not team_name:
        raise TeamSigningParseError("Falta la cabecera `Equipo:` en el mensaje enlazado.")
    if not team_logo_url:
        raise TeamSigningParseError("Falta la cabecera `Logo:` en el mensaje enlazado.")
    if not _contains_non_empty_lines(player_lines):
        raise TeamSigningParseError("El mensaje enlazado no contiene ningún bloque de jugador.")

    if not _looks_like_labelled_format(player_lines, "jugador"):
        raise TeamSigningParseError(
            "La plantilla de jugadores debe usar bloques `Jugador:`, `Tracker:`, `Discord:`, `Epic Name:`, `Rocket In-Game Name:`, `MMR:`."
        )

    players = _parse_labelled_player_blocks(
        player_lines,
        start_line_number=player_start_line,
    )
    if not players:
        raise TeamSigningParseError("El mensaje enlazado no contiene ningún bloque de jugador.")
    if len(players) < MIN_TEAM_SIGNING_PLAYERS or len(players) > MAX_TEAM_SIGNING_PLAYERS:
        raise TeamSigningParseError(
            f"La plantilla de jugadores debe contener entre {MIN_TEAM_SIGNING_PLAYERS} y {MAX_TEAM_SIGNING_PLAYERS} jugadores."
        )
    _ensure_unique_player_discord_names(players)

    return TeamSigningBatch(
        division_name=division_name,
        team_name=team_name,
        team_logo_url=team_logo_url,
        players=sort_team_signing_players(players),
    )


def _parse_labelled_player_blocks(
        content_lines: list[str],
        *,
        start_line_number: int,
) -> list[TeamSigningPlayer]:
    player_blocks = _split_labelled_blocks(
        content_lines,
        start_line_number=start_line_number,
        field_keys=LABELLED_PLAYER_FIELD_KEYS,
        first_field_name="player_name",
        block_label="jugador",
    )
    if len(player_blocks) > MAX_TEAM_SIGNING_PLAYERS:
        raise TeamSigningParseError(
            f"La plantilla de jugadores admite como máximo {MAX_TEAM_SIGNING_PLAYERS} jugadores."
        )

    players: list[TeamSigningPlayer] = []
    for player_index, block in enumerate(player_blocks, start=1):
        payload = {"position": str(player_index)}
        for field_name in LABELLED_PLAYER_FIELD_ORDER:
            field_value = block.values_by_field.get(field_name, "")
            if not field_value and block.has_content:
                label = _label_for_field(field_name, LABELLED_PLAYER_FIELD_KEYS)
                raise TeamSigningParseError(
                    f"Falta un valor para `{label}` en el bloque de jugador cerca de la línea {block.start_line_number}."
                )
            payload[field_name] = field_value

        if not block.has_content:
            continue

        players.append(_build_team_signing_player(payload, block.start_line_number))

    return players


def _build_team_signing_player(
        payload: dict[str, str],
        line_number: int,
) -> TeamSigningPlayer:
    missing_fields = [
        field_name
        for field_name in REQUIRED_PLAYER_FIELDS
        if not payload.get(field_name)
    ]
    if missing_fields:
        missing_fields_label = ", ".join(missing_fields)
        raise TeamSigningParseError(
            f"Faltan campos obligatorios en el bloque del jugador cerca de la línea {line_number}: {missing_fields_label}."
        )

    mmr_value = payload["mmr"]
    if _parse_mmr_sort_value(mmr_value) < 0:
        raise TeamSigningParseError(
            f"El valor de `MMR` no es válido en el bloque cerca de la línea {line_number}: `{mmr_value}`."
        )

    return TeamSigningPlayer(
        player_name=payload["player_name"],
        tracker_url=payload["tracker_url"],
        discord_name=payload["discord_name"],
        epic_name=payload["epic_name"],
        rocket_name=payload["rocket_name"],
        mmr=mmr_value,
    )


def _ensure_unique_player_discord_names(players: list[TeamSigningPlayer]) -> None:
    seen_names: set[str] = set()
    duplicated_names: set[str] = set()
    for player in players:
        normalized_discord_name = _normalize_player_discord_name(player.discord_name)
        if not normalized_discord_name:
            continue
        if normalized_discord_name in seen_names:
            duplicated_names.add(player.discord_name)
            continue
        seen_names.add(normalized_discord_name)

    if duplicated_names:
        duplicated_names_label = ", ".join(sorted(duplicated_names))
        raise TeamSigningParseError(
            f"La plantilla contiene jugadores repetidos en la columna `Discord`: {duplicated_names_label}."
        )


def _normalize_player_discord_name(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]

    return unicodedata.normalize("NFKC", normalized).casefold()
