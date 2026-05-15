from __future__ import annotations

import unicodedata

from bigness_league_bot.application.services.team_signing_models import (
    MAX_TEAM_TECHNICAL_STAFF_MEMBERS,
    TeamSigningParseError,
    TeamTechnicalStaffBatch,
    TeamTechnicalStaffMember,
)
from bigness_league_bot.application.services.team_signing_template import (
    _contains_non_empty_lines,
    _extract_message_metadata_and_body,
    _label_for_field,
    _looks_like_labelled_format,
    _split_labelled_blocks,
    _unwrap_discord_code_block,
)

REQUIRED_TECHNICAL_STAFF_FIELDS = (
    "role_name",
    "discord_id",
)
OPTIONAL_TECHNICAL_STAFF_IDENTITY_FIELDS = ("player_name", "epic_name")
LABELLED_TECHNICAL_STAFF_FIELD_KEYS = {
    "rol": "role_name",
    "player": "player_name",
    "jugador": "player_name",
    "discord id": "discord_id",
    "discord": "discord_id",
    "epic name": "epic_name",
}
LABELLED_TECHNICAL_STAFF_FULL_FIELD_ORDER = (
    "role_name",
    "player_name",
    "discord_id",
    "epic_name",
)
TECHNICAL_STAFF_ROLE_LABELS = {
    "analista": "Analista",
    "analyst": "Analista",
    "captain": "Capitán",
    "capitan": "Capitán",
    "ceo": "CEO",
    "coach": "Coach",
    "manager": "Mánager",
    "second manager": "Segundo Mánager",
    "second_manager": "Segundo Mánager",
    "segundo manager": "Segundo Mánager",
}
TECHNICAL_STAFF_SUPPORTED_ROLES_LABEL = (
    "CEO, Mánager, Segundo Mánager, Coach, Analista, Capitán"
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
        raise TeamSigningParseError("Falta la cabecera `Division:` en el mensaje enlazado.")
    if not team_name:
        raise TeamSigningParseError("Falta la cabecera `Equipo:` en el mensaje enlazado.")
    if not _contains_non_empty_lines(staff_lines):
        raise TeamSigningParseError(
            "El mensaje enlazado no contiene ningún bloque de staff técnico."
        )
    if not _looks_like_labelled_format(staff_lines, "rol"):
        raise TeamSigningParseError(
            "La plantilla de staff técnico debe usar bloques `Rol:`, `Discord ID:` y, si hace falta, `Player:`/`Epic Name:`."
        )

    members = _parse_labelled_technical_staff_blocks(
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


def _parse_labelled_technical_staff_blocks(
        content_lines: list[str],
        *,
        start_line_number: int,
) -> list[TeamTechnicalStaffMember]:
    staff_blocks = _split_labelled_blocks(
        content_lines,
        start_line_number=start_line_number,
        field_keys=LABELLED_TECHNICAL_STAFF_FIELD_KEYS,
        first_field_name="role_name",
        block_label="staff tecnico",
    )

    members: list[TeamTechnicalStaffMember] = []
    for block in staff_blocks:
        if not block.has_content:
            continue

        present_fields = frozenset(block.values_by_field)
        if not frozenset(REQUIRED_TECHNICAL_STAFF_FIELDS) <= present_fields:
            raise TeamSigningParseError(
                "Cada bloque de staff técnico debe contener al menos `Rol` y `Discord ID`."
            )

        payload: dict[str, str] = {}
        for field_name in LABELLED_TECHNICAL_STAFF_FULL_FIELD_ORDER:
            field_value = block.values_by_field.get(field_name, "")
            if not field_value and field_name in present_fields:
                label = _label_for_field(
                    field_name,
                    LABELLED_TECHNICAL_STAFF_FIELD_KEYS,
                )
                raise TeamSigningParseError(
                    f"Falta un valor para `{label}` en el bloque de staff técnico cerca de la linea {block.start_line_number}."
                )
            payload[field_name] = field_value

        members.extend(
            _build_team_technical_staff_members(
                payload,
                block.start_line_number,
            )
        )

    _ensure_unique_technical_staff_roles(members)
    if len(members) > MAX_TEAM_TECHNICAL_STAFF_MEMBERS:
        raise TeamSigningParseError(
            f"La plantilla de staff técnico admite como máximo {MAX_TEAM_TECHNICAL_STAFF_MEMBERS} cargos."
        )

    return members


def _build_team_technical_staff_members(
        payload: dict[str, str],
        line_number: int,
) -> tuple[TeamTechnicalStaffMember, ...]:
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

    identity_fields_present = [
        field_name
        for field_name in OPTIONAL_TECHNICAL_STAFF_IDENTITY_FIELDS
        if payload.get(field_name)
    ]
    if identity_fields_present and len(identity_fields_present) != len(OPTIONAL_TECHNICAL_STAFF_IDENTITY_FIELDS):
        raise TeamSigningParseError(
            f"El bloque de staff técnico cerca de la línea {line_number} debe indicar `Player` y `Epic Name` juntos, o dejar ambos vacíos para resolverlos desde la plantilla de jugadores."
        )

    role_names = _parse_technical_staff_role_names(payload["role_name"], line_number)
    return tuple(
        TeamTechnicalStaffMember(
            role_name=role_name,
            player_name=payload["player_name"],
            discord_id=payload["discord_id"],
            epic_name=payload["epic_name"],
        )
        for role_name in role_names
    )


def _parse_technical_staff_role_names(value: str, line_number: int) -> tuple[str, ...]:
    role_names: list[str] = []
    seen_role_names: set[str] = set()
    for raw_role_name in (role_name.strip() for role_name in value.split(",")):
        if not raw_role_name:
            continue

        role_name = _resolve_technical_staff_role_label(raw_role_name)
        if role_name is None:
            raise TeamSigningParseError(
                f"El cargo de staff técnico `{raw_role_name}` no está soportado cerca de la línea {line_number}. Cargos permitidos: {TECHNICAL_STAFF_SUPPORTED_ROLES_LABEL}."
            )

        normalized_role_name = _normalize_technical_staff_role_lookup(role_name)
        if normalized_role_name in seen_role_names:
            raise TeamSigningParseError(
                f"El cargo de staff técnico `{role_name}` está repetido cerca de la línea {line_number}."
            )
        seen_role_names.add(normalized_role_name)
        role_names.append(role_name)

    if not role_names:
        raise TeamSigningParseError(
            f"Falta un valor válido para `Rol` en el bloque de staff técnico cerca de la línea {line_number}."
        )
    return tuple(role_names)


def _ensure_unique_technical_staff_roles(members: list[TeamTechnicalStaffMember]) -> None:
    seen_roles: dict[str, str] = {}
    duplicated_roles: set[str] = set()
    for member in members:
        normalized_role_name = _normalize_technical_staff_role_lookup(member.role_name)
        previous_role_name = seen_roles.get(normalized_role_name)
        if previous_role_name is not None:
            duplicated_roles.add(previous_role_name)
            continue
        seen_roles[normalized_role_name] = member.role_name

    if duplicated_roles:
        duplicated_roles_label = ", ".join(sorted(duplicated_roles))
        raise TeamSigningParseError(
            f"La plantilla contiene cargos de staff técnico repetidos: {duplicated_roles_label}."
        )


def _resolve_technical_staff_role_label(value: str) -> str | None:
    return TECHNICAL_STAFF_ROLE_LABELS.get(_normalize_technical_staff_role_lookup(value))


def _normalize_technical_staff_role_lookup(value: str) -> str:
    normalized = " ".join(value.casefold().strip().split())
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )
    return normalized
