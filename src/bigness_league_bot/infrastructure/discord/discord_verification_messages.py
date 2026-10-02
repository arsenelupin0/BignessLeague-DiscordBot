from __future__ import annotations

from collections.abc import Iterable
from textwrap import wrap

import discord

from bigness_league_bot.application.services.discord_verification import (
    MemberVerification, TeamVerification, VerificationStatus,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

PAGE_LIMIT = 1900
SINGLE_MESSAGE_LIMIT = 2000


def _safe(value: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(" ".join(value.split())[:180]))


def build_verification_pages(
        reports: Iterable[TeamVerification],
        *,
        localizer: LocalizationService,
        locale: str | discord.Locale,
        missing_only: bool = False,
) -> tuple[str, ...]:
    reports = tuple(sorted(reports, key=lambda r: (r.division_name.casefold(), r.team_name.casefold())))
    keys = I18N.messages.discord_verification

    def tr(key, **params) -> str:
        return localizer.translate(key, locale=locale, **params)

    members = tuple(m for r in reports for m in r.members)
    summary = tr(
        keys.summary, teams=len(reports), total=len(members),
        present=sum(m.status == VerificationStatus.PRESENT for m in members),
        missing=sum(m.status == VerificationStatus.MISSING for m in members),
        review=sum(m.status in {VerificationStatus.INVALID, VerificationStatus.AMBIGUOUS} for m in members),
        roles=sum(bool(m.missing_roles) for m in members),
    )
    intro = tr(keys.filtered_title if missing_only else keys.title) + "\n" + summary
    if not missing_only:
        intro += "\n" + tr(keys.legend)
    pages = [intro]
    full_sections = [intro]

    def member_line(member: MemberVerification) -> str:
        reference = f"<@{member.member_id}> · `{member.member_id}`" if member.member_id else tr(keys.no_resolved_id)
        sheet_values = " / ".join(_safe(v) or "—" for v in member.sheet_values)
        identity = tr(keys.identity, player=_safe(member.player_name) or "—", reference=reference, sheet=sheet_values)
        status_key = {
            VerificationStatus.PRESENT: keys.present,
            VerificationStatus.MISSING: keys.missing,
            VerificationStatus.INVALID: keys.invalid,
            VerificationStatus.AMBIGUOUS: keys.ambiguous,
        }[member.status]
        if member.missing_roles:
            status = tr(keys.missing_roles, roles=", ".join(f"<@&{r.role_id}>" for r in member.missing_roles))
        else:
            status = tr(status_key)
        if member.candidate_ids:
            status += " " + ", ".join(f"<@{i}>" for i in member.candidate_ids[:10])
        return f"- {identity}\n  {status}"

    for report in reports:
        heading = tr(keys.team_heading, division=_safe(report.division_name), team=_safe(report.team_name))
        selected = tuple(sorted(
            (m for m in report.members if not missing_only or m.status == VerificationStatus.MISSING),
            key=lambda m: (
                0 if m.status == VerificationStatus.MISSING else
                1 if m.status in {VerificationStatus.AMBIGUOUS, VerificationStatus.INVALID} else
                2 if m.missing_roles else 3,
                m.player_name.casefold(),
            ),
        ))
        if missing_only:
            lines = [member_line(m) for m in selected] or [tr(keys.no_missing)]
        else:
            lines = [tr(
                keys.team_summary, total=len(report.members),
                present=sum(m.status == VerificationStatus.PRESENT for m in report.members),
                missing=sum(m.status == VerificationStatus.MISSING for m in report.members),
            )]
            lines.extend(tr(keys.unavailable_role, role=_safe(name)) for name in report.unavailable_roles)
            lines.extend(member_line(m) for m in selected)
            if not selected:
                lines.append(tr(keys.empty_roster))
        full_sections.append(heading + "\n" + "\n".join(lines))
        section = heading
        for line in lines:
            # Keep pathological sheet labels or many aliases within Discord's limit.
            capacity = PAGE_LIMIT - len(heading) - 1
            fragments = [fragment for row in line.splitlines()
                         for fragment in (wrap(row, width=capacity, replace_whitespace=False) or [""])]
            for fragment in fragments:
                if len(section) + len(fragment) + 1 > PAGE_LIMIT:
                    pages.append(section)
                    section = heading
                section += "\n" + fragment
        if len(pages[-1]) + len(section) + 2 <= PAGE_LIMIT:
            pages[-1] += "\n\n" + section
        else:
            pages.append(section)
    if not reports:
        empty_message = tr(keys.no_teams)
        pages[-1] += "\n\n" + empty_message
        full_sections.append(empty_message)
    full_report = "\n\n".join(full_sections)
    if len(full_report) <= SINGLE_MESSAGE_LIMIT:
        return (full_report,)
    return tuple(pages)
