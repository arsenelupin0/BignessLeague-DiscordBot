from __future__ import annotations

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
    "discord_name",
)
LABELLED_TECHNICAL_STAFF_FIELD_KEYS = {
    "rol": "role_name",
    "discord": "discord_name",
    "epic name": "epic_name",
    "rocket in-game name": "rocket_name",
}
LABELLED_TECHNICAL_STAFF_FULL_FIELD_ORDER = tuple(
    LABELLED_TECHNICAL_STAFF_FIELD_KEYS.values()
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
    if not _looks_like_labelled_format(staff_lines, "rol"):
        raise TeamSigningParseError(
            "La plantilla de staff técnico debe usar bloques `Rol:`, `Discord:`, `Epic Name:`, `Rocket In-Game Name:`."
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
        block_label="staff técnico",
    )
    if len(staff_blocks) > MAX_TEAM_TECHNICAL_STAFF_MEMBERS:
        raise TeamSigningParseError(
            f"La plantilla de staff técnico admite como máximo {MAX_TEAM_TECHNICAL_STAFF_MEMBERS} cargos."
        )

    members: list[TeamTechnicalStaffMember] = []
    for block in staff_blocks:
        if not block.has_content:
            continue

        present_fields = frozenset(block.values_by_field)
        if present_fields != frozenset(LABELLED_TECHNICAL_STAFF_FULL_FIELD_ORDER):
            raise TeamSigningParseError(
                "Cada bloque de staff técnico debe contener `Rol`, `Discord`, `Epic Name` y `Rocket In-Game Name`."
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
                    f"Falta un valor para `{label}` en el bloque de staff técnico cerca de la línea {block.start_line_number}."
                )
            payload[field_name] = field_value

        members.append(
            _build_team_technical_staff_member(
                payload,
                block.start_line_number,
            )
        )

    return members


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
