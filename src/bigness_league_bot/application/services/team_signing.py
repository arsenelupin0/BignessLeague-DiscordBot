from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import unicodedata

MAX_TEAM_SIGNING_PLAYERS = 6
MMR_DIGITS_PATTERN = re.compile(r"\d+")

MESSAGE_METADATA_KEYS = {
    "division": "division_name",
    "equipo": "team_name",
}
REQUIRED_PLAYER_FIELDS = (
    "position",
    "player_name",
    "tracker_url",
    "discord_name",
    "epic_name",
    "rocket_name",
    "mmr",
)
REQUIRED_TECHNICAL_STAFF_FIELDS = (
    "role_name",
    "discord_name",
)
COMPACT_PLAYER_HEADERS = (
    "jugador",
    "tracker",
    "discord",
    "epic name",
    "rocket in-game name",
    "mmr",
)
COMPACT_PLAYER_FIELD_ORDER = (
    "player_name",
    "tracker_url",
    "discord_name",
    "epic_name",
    "rocket_name",
    "mmr",
)
COMPACT_TECHNICAL_STAFF_HEADERS = (
    "rol",
    "discord",
    "epic name",
    "rocket in-game name",
)
COMPACT_TECHNICAL_STAFF_REQUIRED_FIELD_ORDER = (
    "role_name",
    "discord_name",
)
COMPACT_TECHNICAL_STAFF_OPTIONAL_FIELD_ORDER = (
    "epic_name",
    "rocket_name",
)


class TeamSigningParseError(ValueError):
    """Raised when the imported signing message does not follow the expected format."""


class TeamSigningCapacityError(ValueError):
    """Raised when the roster cannot fit the requested signings."""

    def __init__(self, *, capacity: int, existing_count: int, requested_count: int) -> None:
        super().__init__("team_signing_capacity_exceeded")
        self.capacity = capacity
        self.existing_count = existing_count
        self.requested_count = requested_count

    @property
    def available_slots(self) -> int:
        return max(self.capacity - self.existing_count, 0)


def _normalize_value(value: str | None) -> str:
    if value is None:
        return ""

    return " ".join(str(value).split())


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(without_accents.split())


def _parse_mmr_sort_value(value: str) -> int:
    matches = MMR_DIGITS_PATTERN.findall(value)
    if not matches:
        return -1

    return int("".join(matches))


def _unwrap_discord_code_block(content: str) -> str:
    lines = content.strip().splitlines()
    if (
            len(lines) >= 2
            and lines[0].strip().startswith("```")
            and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1])

    return content


@dataclass(frozen=True, slots=True)
class TeamSigningPlayer:
    player_name: str
    tracker_url: str
    discord_name: str
    epic_name: str
    rocket_name: str
    mmr: str

    @property
    def mmr_sort_value(self) -> int:
        return _parse_mmr_sort_value(self.mmr)


@dataclass(frozen=True, slots=True)
class TeamSigningBatch:
    division_name: str
    team_name: str
    players: tuple[TeamSigningPlayer, ...]


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffMember:
    role_name: str
    discord_name: str
    epic_name: str
    rocket_name: str


@dataclass(frozen=True, slots=True)
class TeamTechnicalStaffBatch:
    division_name: str
    team_name: str
    members: tuple[TeamTechnicalStaffMember, ...]


def parse_team_signing_message(content: str) -> TeamSigningBatch:
    content = _unwrap_discord_code_block(content)
    content_lines = content.splitlines()
    metadata, player_lines, player_start_line = _extract_message_metadata_and_body(
        content_lines
    )

    division_name = metadata.get("division_name", "")
    team_name = metadata.get("team_name", "")
    if not division_name:
        raise TeamSigningParseError("Falta la cabecera `División:` en el mensaje enlazado.")
    if not team_name:
        raise TeamSigningParseError("Falta la cabecera `Equipo:` en el mensaje enlazado.")
    if not _contains_non_empty_lines(player_lines):
        raise TeamSigningParseError("El mensaje enlazado no contiene ningún bloque de jugador.")

    if not _looks_like_compact_player_format(player_lines):
        raise TeamSigningParseError(
            "La plantilla de jugadores debe empezar con las cabeceras `Jugador`, `Tracker`, `Discord`, `Epic Name`, `Rocket In-Game Name`, `MMR`."
        )

    players = _parse_compact_player_blocks(
        player_lines,
        start_line_number=player_start_line,
    )
    if not players:
        raise TeamSigningParseError("El mensaje enlazado no contiene ningún bloque de jugador.")

    return TeamSigningBatch(
        division_name=division_name,
        team_name=team_name,
        players=sort_team_signing_players(players),
    )


def parse_team_technical_staff_message(content: str) -> TeamTechnicalStaffBatch:
    content = _unwrap_discord_code_block(content)
    content_lines = content.splitlines()
    metadata, staff_lines, staff_start_line = _extract_message_metadata_and_body(
        content_lines
    )

    division_name = metadata.get("division_name", "")
    team_name = metadata.get("team_name", "")
    if not division_name:
        raise TeamSigningParseError("Falta la cabecera `División:` en el mensaje enlazado.")
    if not team_name:
        raise TeamSigningParseError("Falta la cabecera `Equipo:` en el mensaje enlazado.")
    if not _contains_non_empty_lines(staff_lines):
        raise TeamSigningParseError(
            "El mensaje enlazado no contiene ningún bloque de staff técnico."
        )
    if not _looks_like_compact_technical_staff_format(staff_lines):
        raise TeamSigningParseError(
            "La plantilla de staff técnico debe empezar con las cabeceras `Rol`, `Discord`, `Epic Name`, `Rocket In-Game Name`."
        )

    members = _parse_compact_technical_staff_blocks(
        staff_lines,
        start_line_number=staff_start_line,
    )
    if not members:
        raise TeamSigningParseError(
            "El mensaje enlazado no contiene ningún bloque de staff técnico."
        )

    return TeamTechnicalStaffBatch(
        division_name=division_name,
        team_name=team_name,
        members=tuple(members),
    )


def sort_team_signing_players(
        players: Iterable[TeamSigningPlayer],
) -> tuple[TeamSigningPlayer, ...]:
    return tuple(
        sorted(
            players,
            key=lambda player: (
                player.mmr_sort_value,
                player.player_name.casefold(),
            ),
            reverse=True,
        )
    )


def merge_team_signing_players(
        existing_players: Iterable[TeamSigningPlayer],
        incoming_players: Iterable[TeamSigningPlayer],
        *,
        capacity: int = MAX_TEAM_SIGNING_PLAYERS,
) -> tuple[TeamSigningPlayer, ...]:
    existing = tuple(existing_players)
    incoming = tuple(incoming_players)
    merged_players = (*existing, *incoming)
    if len(merged_players) > capacity:
        raise TeamSigningCapacityError(
            capacity=capacity,
            existing_count=len(existing),
            requested_count=len(incoming),
        )

    return sort_team_signing_players(merged_players)


def _extract_message_metadata_and_body(
        content_lines: list[str],
) -> tuple[dict[str, str], list[str], int]:
    metadata: dict[str, str] = {}
    body_start_index = len(content_lines)

    for line_index, raw_line in enumerate(content_lines):
        line = raw_line.strip()
        if not line:
            continue

        if ":" in line:
            raw_key, raw_value = line.split(":", 1)
            key = _normalize_key(raw_key)
            value = _normalize_value(raw_value)
            if key in MESSAGE_METADATA_KEYS:
                if not value:
                    raise TeamSigningParseError(
                        f"La línea {line_index + 1} no contiene un valor válido para `{raw_key.strip()}`."
                    )

                metadata[MESSAGE_METADATA_KEYS[key]] = value
                continue

        body_start_index = line_index
        break

    if body_start_index >= len(content_lines):
        return metadata, [], len(content_lines) + 1

    return metadata, content_lines[body_start_index:], body_start_index + 1


def _looks_like_compact_player_format(content_lines: list[str]) -> bool:
    non_empty_lines = [line.strip() for line in content_lines if line.strip()]
    if len(non_empty_lines) < len(COMPACT_PLAYER_HEADERS):
        return False

    normalized_headers = tuple(
        _normalize_key(line)
        for line in non_empty_lines[:len(COMPACT_PLAYER_HEADERS)]
    )
    return normalized_headers == COMPACT_PLAYER_HEADERS


def _parse_compact_player_blocks(
        content_lines: list[str],
        *,
        start_line_number: int,
) -> list[TeamSigningPlayer]:
    indexed_lines = [
        (start_line_number + index, raw_line.strip())
        for index, raw_line in enumerate(content_lines)
        if raw_line.strip()
    ]
    header_count = len(COMPACT_PLAYER_HEADERS)
    if len(indexed_lines) < header_count:
        raise TeamSigningParseError(
            "La plantilla compacta de jugadores no contiene todas las cabeceras esperadas."
        )

    normalized_headers = tuple(
        _normalize_key(line)
        for _, line in indexed_lines[:header_count]
    )
    if normalized_headers != COMPACT_PLAYER_HEADERS:
        raise TeamSigningParseError(
            "La plantilla compacta de jugadores debe empezar con las cabeceras `Jugador`, `Tracker`, `Discord`, `Epic Name`, `Rocket In-Game Name`, `MMR`."
        )

    data_lines = indexed_lines[header_count:]
    while data_lines and _is_visual_separator_line(data_lines[0][1]):
        data_lines = data_lines[1:]

    if not data_lines:
        raise TeamSigningParseError(
            "La plantilla compacta no contiene ningún jugador después de las cabeceras."
        )

    field_count = len(COMPACT_PLAYER_FIELD_ORDER)
    if len(data_lines) % field_count != 0:
        raise TeamSigningParseError(
            "La plantilla compacta de jugadores debe contener bloques completos de 6 líneas por jugador."
        )

    players: list[TeamSigningPlayer] = []
    for player_index, offset in enumerate(range(0, len(data_lines), field_count), start=1):
        payload = {"position": str(player_index)}
        chunk = data_lines[offset:offset + field_count]
        for field_name, (line_number, value) in zip(COMPACT_PLAYER_FIELD_ORDER, chunk, strict=True):
            normalized_value = _normalize_value(value)
            if not normalized_value:
                raise TeamSigningParseError(
                    f"La línea {line_number} no contiene un valor válido."
                )
            payload[field_name] = normalized_value

        players.append(_build_team_signing_player(payload, chunk[-1][0]))

    return players


def _looks_like_compact_technical_staff_format(content_lines: list[str]) -> bool:
    non_empty_lines = [line.strip() for line in content_lines if line.strip()]
    if len(non_empty_lines) < len(COMPACT_TECHNICAL_STAFF_HEADERS):
        return False

    normalized_headers = tuple(
        _normalize_key(line)
        for line in non_empty_lines[:len(COMPACT_TECHNICAL_STAFF_HEADERS)]
    )
    return normalized_headers == COMPACT_TECHNICAL_STAFF_HEADERS


def _parse_compact_technical_staff_blocks(
        content_lines: list[str],
        *,
        start_line_number: int,
) -> list[TeamTechnicalStaffMember]:
    entry_blocks = _split_compact_entry_blocks(
        content_lines,
        header_count=len(COMPACT_TECHNICAL_STAFF_HEADERS),
        start_line_number=start_line_number,
    )
    if not entry_blocks:
        raise TeamSigningParseError(
            "La plantilla compacta de staff técnico no contiene ningún bloque después de las cabeceras."
        )

    members: list[TeamTechnicalStaffMember] = []
    required_field_count = len(COMPACT_TECHNICAL_STAFF_REQUIRED_FIELD_ORDER)
    full_field_count = required_field_count + len(COMPACT_TECHNICAL_STAFF_OPTIONAL_FIELD_ORDER)
    for entry_block in entry_blocks:
        if len(entry_block) not in {required_field_count, full_field_count}:
            raise TeamSigningParseError(
                "Cada bloque de staff técnico debe contener 2 líneas (`Rol`, `Discord`) o 4 líneas (añadiendo `Epic Name` y `Rocket In-Game Name`)."
            )

        payload: dict[str, str] = {}
        for field_name, (line_number, value) in zip(
                COMPACT_TECHNICAL_STAFF_REQUIRED_FIELD_ORDER,
                entry_block[:required_field_count],
                strict=True,
        ):
            normalized_value = _normalize_value(value)
            if not normalized_value:
                raise TeamSigningParseError(
                    f"La línea {line_number} no contiene un valor válido."
                )
            payload[field_name] = normalized_value

        optional_lines = entry_block[required_field_count:]
        for field_name, (line_number, value) in zip(
                COMPACT_TECHNICAL_STAFF_OPTIONAL_FIELD_ORDER[:len(optional_lines)],
                optional_lines,
                strict=True,
        ):
            normalized_value = _normalize_value(value)
            if not normalized_value:
                raise TeamSigningParseError(
                    f"La línea {line_number} no contiene un valor válido."
                )
            payload[field_name] = normalized_value

        members.append(
            _build_team_technical_staff_member(
                payload,
                entry_block[-1][0],
            )
        )

    return members


def _split_compact_entry_blocks(
        content_lines: list[str],
        *,
        header_count: int,
        start_line_number: int,
) -> list[list[tuple[int, str]]]:
    entry_blocks: list[list[tuple[int, str]]] = []
    current_block: list[tuple[int, str]] = []
    for line_offset, raw_line in enumerate(content_lines[header_count:], start=header_count):
        line_number = start_line_number + line_offset
        line = raw_line.strip()
        if not line:
            if current_block:
                entry_blocks.append(current_block)
                current_block = []
            continue

        if _is_visual_separator_line(line):
            if current_block:
                entry_blocks.append(current_block)
                current_block = []
            continue

        current_block.append((line_number, line))

    if current_block:
        entry_blocks.append(current_block)

    return entry_blocks


def _contains_non_empty_lines(content_lines: list[str]) -> bool:
    return any(raw_line.strip() for raw_line in content_lines)


def _is_visual_separator_line(value: str) -> bool:
    stripped_value = "".join(character for character in value.strip() if not character.isspace())
    if not stripped_value:
        return False

    return not any(character.isalnum() for character in stripped_value)


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


def _build_team_technical_staff_member(
        payload: dict[str, str],
        line_number: int,
) -> TeamTechnicalStaffMember:
    missing_fields = [
        field_name
        for field_name in REQUIRED_TECHNICAL_STAFF_FIELDS
        if not payload.get(field_name)
    ]
    if missing_fields:
        missing_fields_label = ", ".join(missing_fields)
        raise TeamSigningParseError(
            f"Faltan campos obligatorios en el bloque de staff técnico cerca de la línea {line_number}: {missing_fields_label}."
        )

    return TeamTechnicalStaffMember(
        role_name=payload["role_name"],
        discord_name=payload["discord_name"],
        epic_name=payload.get("epic_name", ""),
        rocket_name=payload.get("rocket_name", ""),
    )
