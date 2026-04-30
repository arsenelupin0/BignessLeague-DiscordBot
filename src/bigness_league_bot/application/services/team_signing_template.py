from __future__ import annotations

from dataclasses import dataclass

import unicodedata

from bigness_league_bot.application.services.team_signing_models import (
    TeamSigningParseError,
)

MESSAGE_METADATA_KEYS = {
    "division": "division_name",
    "equipo": "team_name",
    "logo": "team_logo_url",
}


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


def _unwrap_discord_code_block(content: str) -> str:
    lines = content.strip().splitlines()
    if (
            len(lines) >= 2
            and lines[0].strip().startswith("```")
            and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1])

    return content


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
                    if key == "logo":
                        continue
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


def _contains_non_empty_lines(content_lines: list[str]) -> bool:
    return any(raw_line.strip() for raw_line in content_lines)


def _is_visual_separator_line(value: str) -> bool:
    stripped_value = "".join(character for character in value.strip() if not character.isspace())
    if not stripped_value:
        return False

    return not any(character.isalnum() for character in stripped_value)


def _looks_like_labelled_format(content_lines: list[str], expected_first_key: str) -> bool:
    for raw_line in content_lines:
        line = raw_line.strip()
        if not line or _is_visual_separator_line(line):
            continue
        if ":" not in line:
            return False

        raw_key, _ = line.split(":", 1)
        return _normalize_key(raw_key) == expected_first_key

    return False


@dataclass(frozen=True, slots=True)
class LabelledTemplateBlock:
    start_line_number: int
    values_by_field: dict[str, str]

    @property
    def has_content(self) -> bool:
        return any(self.values_by_field.values())


def _split_labelled_blocks(
        content_lines: list[str],
        *,
        start_line_number: int,
        field_keys: dict[str, str],
        first_field_name: str,
        block_label: str,
) -> list[LabelledTemplateBlock]:
    blocks: list[LabelledTemplateBlock] = []
    current_values: dict[str, str] = {}
    current_start_line_number = start_line_number

    for line_offset, raw_line in enumerate(content_lines):
        line_number = start_line_number + line_offset
        line = raw_line.strip()
        if not line or _is_visual_separator_line(line):
            continue
        if ":" not in line:
            raise TeamSigningParseError(
                f"La línea {line_number} debe usar el formato `Campo: valor`."
            )

        raw_key, raw_value = line.split(":", 1)
        normalized_key = _normalize_key(raw_key)
        field_name = _resolve_labelled_field_name(
            normalized_key,
            field_keys=field_keys,
            raw_key=raw_key,
            line_number=line_number,
            block_label=block_label,
        )
        if field_name == first_field_name and current_values:
            blocks.append(
                LabelledTemplateBlock(
                    start_line_number=current_start_line_number,
                    values_by_field=current_values,
                )
            )
            current_values = {}
            current_start_line_number = line_number
        elif not current_values:
            current_start_line_number = line_number

        current_values[field_name] = _normalize_value(raw_value)

    if current_values:
        blocks.append(
            LabelledTemplateBlock(
                start_line_number=current_start_line_number,
                values_by_field=current_values,
            )
        )

    return blocks


def _resolve_labelled_field_name(
        normalized_key: str,
        *,
        field_keys: dict[str, str],
        raw_key: str,
        line_number: int,
        block_label: str,
) -> str:
    field_name = field_keys.get(normalized_key)
    if field_name is None:
        raise TeamSigningParseError(
            f"La línea {line_number} contiene un campo de {block_label} no soportado: `{raw_key.strip()}`."
        )

    return field_name


def _label_for_field(field_name: str, field_keys: dict[str, str]) -> str:
    for label, mapped_field_name in field_keys.items():
        if mapped_field_name == field_name:
            return label

    return field_name
