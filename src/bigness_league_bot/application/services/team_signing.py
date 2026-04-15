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
MESSAGE_PLAYER_KEYS = {
    "pos": "position",
    "jugador": "player_name",
    "tracker": "tracker_url",
    "discord": "discord_name",
    "epic name": "epic_name",
    "rocket in-game name": "rocket_name",
    "mmr": "mmr",
}
MESSAGE_TECHNICAL_STAFF_KEYS = {
    "rol": "role_name",
    "discord": "discord_name",
    "epic name": "epic_name",
    "rocket in-game name": "rocket_name",
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
    metadata: dict[str, str] = {}
    current_player: dict[str, str] | None = None
    players: list[TeamSigningPlayer] = []

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if ":" not in line:
            raise TeamSigningParseError(
                f"La linea {line_number} no sigue el formato `Campo: Valor`."
            )

        raw_key, raw_value = line.split(":", 1)
        key = _normalize_key(raw_key)
        value = _normalize_value(raw_value)
        if not value:
            raise TeamSigningParseError(
                f"La linea {line_number} no contiene un valor valido para `{raw_key.strip()}`."
            )

        if key in MESSAGE_METADATA_KEYS:
            if current_player is not None:
                raise TeamSigningParseError(
                    f"La linea {line_number} aparece despues del bloque de jugadores."
                )

            metadata[MESSAGE_METADATA_KEYS[key]] = value
            continue

        if key == "pos":
            if current_player is not None:
                players.append(_build_team_signing_player(current_player, line_number - 1))

            current_player = {"position": value}
            continue

        if key not in MESSAGE_PLAYER_KEYS:
            raise TeamSigningParseError(
                f"La linea {line_number} usa un campo no reconocido: `{raw_key.strip()}`."
            )

        if current_player is None:
            raise TeamSigningParseError(
                f"La linea {line_number} aparece antes de definir `Pos:`."
            )

        field_name = MESSAGE_PLAYER_KEYS[key]
        if field_name in current_player:
            raise TeamSigningParseError(
                f"El campo `{raw_key.strip()}` esta repetido en el bloque actual."
            )

        current_player[field_name] = value

    if current_player is not None:
        players.append(_build_team_signing_player(current_player, len(content.splitlines())))

    division_name = metadata.get("division_name", "")
    team_name = metadata.get("team_name", "")
    if not division_name:
        raise TeamSigningParseError("Falta la cabecera `Division:` en el mensaje enlazado.")
    if not team_name:
        raise TeamSigningParseError("Falta la cabecera `Equipo:` en el mensaje enlazado.")
    if not players:
        raise TeamSigningParseError("El mensaje enlazado no contiene ningun bloque de jugador.")

    return TeamSigningBatch(
        division_name=division_name,
        team_name=team_name,
        players=sort_team_signing_players(players),
    )


def parse_team_technical_staff_message(content: str) -> TeamTechnicalStaffBatch:
    metadata: dict[str, str] = {}
    current_member: dict[str, str] | None = None
    members: list[TeamTechnicalStaffMember] = []

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if ":" not in line:
            raise TeamSigningParseError(
                f"La linea {line_number} no sigue el formato `Campo: Valor`."
            )

        raw_key, raw_value = line.split(":", 1)
        key = _normalize_key(raw_key)
        value = _normalize_value(raw_value)
        if not value:
            raise TeamSigningParseError(
                f"La linea {line_number} no contiene un valor valido para `{raw_key.strip()}`."
            )

        if key in MESSAGE_METADATA_KEYS:
            if current_member is not None:
                raise TeamSigningParseError(
                    f"La linea {line_number} aparece despues del bloque de staff tecnico."
                )

            metadata[MESSAGE_METADATA_KEYS[key]] = value
            continue

        if key == "rol":
            if current_member is not None:
                members.append(
                    _build_team_technical_staff_member(current_member, line_number - 1)
                )

            current_member = {"role_name": value}
            continue

        if key not in MESSAGE_TECHNICAL_STAFF_KEYS:
            raise TeamSigningParseError(
                f"La linea {line_number} usa un campo no reconocido: `{raw_key.strip()}`."
            )

        if current_member is None:
            raise TeamSigningParseError(
                f"La linea {line_number} aparece antes de definir `Rol:`."
            )

        field_name = MESSAGE_TECHNICAL_STAFF_KEYS[key]
        if field_name in current_member:
            raise TeamSigningParseError(
                f"El campo `{raw_key.strip()}` esta repetido en el bloque actual."
            )

        current_member[field_name] = value

    if current_member is not None:
        members.append(
            _build_team_technical_staff_member(current_member, len(content.splitlines()))
        )

    division_name = metadata.get("division_name", "")
    team_name = metadata.get("team_name", "")
    if not division_name:
        raise TeamSigningParseError("Falta la cabecera `Division:` en el mensaje enlazado.")
    if not team_name:
        raise TeamSigningParseError("Falta la cabecera `Equipo:` en el mensaje enlazado.")
    if not members:
        raise TeamSigningParseError(
            "El mensaje enlazado no contiene ningun bloque de staff tecnico."
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
            f"Faltan campos obligatorios en el bloque del jugador cerca de la linea {line_number}: {missing_fields_label}."
        )

    mmr_value = payload["mmr"]
    if _parse_mmr_sort_value(mmr_value) < 0:
        raise TeamSigningParseError(
            f"El valor de `MMR` no es valido en el bloque cerca de la linea {line_number}: `{mmr_value}`."
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
            f"Faltan campos obligatorios en el bloque de staff tecnico cerca de la linea {line_number}: {missing_fields_label}."
        )

    return TeamTechnicalStaffMember(
        role_name=payload["role_name"],
        discord_name=payload["discord_name"],
        epic_name=payload["epic_name"],
        rocket_name=payload["rocket_name"],
    )
