from __future__ import annotations

from collections.abc import Iterable

import discord

from bigness_league_bot.application.services.discord_verification import (
    ExpectedRole, IdentityResolution, MemberSnapshot, TeamVerification,
    collect_roster_identities, parse_discord_id, verify_team,
)
from bigness_league_bot.application.services.team_profile import TeamProfile
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import localize
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.discord.channel_access_management import ChannelAccessRoleCatalog
from bigness_league_bot.infrastructure.discord.team_member_lookup import (
    index_members_by_lookup_keys, normalize_member_lookup_text,
)
from bigness_league_bot.infrastructure.discord.team_staff_roles import (
    filter_team_staff_role_names_for_player_status, normalize_team_staff_role_name,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


async def verify_discord_rosters(
        guild: discord.Guild,
        profiles: Iterable[TeamProfile],
        *,
        settings: Settings,
        role_catalog: ChannelAccessRoleCatalog,
) -> tuple[TeamVerification, ...]:
    # fetch_members results need not populate guild.get_member's gateway cache.
    # Never classify absences using an incomplete cache after a request fails.
    try:
        members = tuple([member async for member in guild.fetch_members(limit=None)])
        by_id = {member.id: member for member in members}
        by_name = index_members_by_lookup_keys(members)
        staff_ids = {
            "ceo": settings.staff_ceo_role_id,
            "analyst": settings.staff_analyst_role_id,
            "coach": settings.staff_coach_role_id,
            "manager": settings.staff_manager_role_id,
            "second_manager": settings.staff_second_manager_role_id,
            "captain": settings.staff_captain_role_id,
        }
        team_roles: dict[str, list[discord.Role]] = {}
        for role in role_catalog.roles:
            team_roles.setdefault(normalize_member_lookup_text(role.name), []).append(role)

        def configured_role(role_id: int, label: str) -> ExpectedRole:
            role = guild.get_role(role_id)
            return ExpectedRole(role.name if role else label, role.id if role else None)

        reports: list[TeamVerification] = []
        for profile in profiles:
            identities = collect_roster_identities(profile)
            resolved = []
            for identity in identities:
                member_id = parse_discord_id(identity.sheet_value)
                if member_id is not None:
                    if member_id not in by_id:
                        try:
                            by_id[member_id] = await guild.fetch_member(member_id)
                        except discord.NotFound:
                            by_id[member_id] = None
                    member = by_id[member_id]
                    matches = (member,) if member else ()
                else:
                    matches = by_name.get(normalize_member_lookup_text(identity.sheet_value), ())
                resolved.append((identity, matches))

            player_ids = {
                matches[0].id for identity, matches in resolved
                if identity.is_player and len(matches) == 1
            }
            roles = team_roles.get(normalize_member_lookup_text(profile.team_name), [])
            team_role = ExpectedRole(profile.team_name, roles[0].id if len(roles) == 1 else None)
            resolutions = []
            for identity, matches in resolved:
                expected = [team_role, configured_role(settings.participant_role_id, str(settings.participant_role_id))]
                is_player = identity.is_player or (len(matches) == 1 and matches[0].id in player_ids)
                if is_player:
                    expected.append(configured_role(settings.player_role_id, str(settings.player_role_id)))
                for name in filter_team_staff_role_names_for_player_status(
                        identity.staff_role_names, is_player_in_same_team=is_player,
                ):
                    key = normalize_team_staff_role_name(name)
                    if key in staff_ids:
                        expected.append(configured_role(staff_ids[key], name))
                resolutions.append(IdentityResolution(
                    identity=identity,
                    matches=tuple(MemberSnapshot(m.id, frozenset(r.id for r in m.roles)) for m in matches),
                    expected_roles=tuple(expected),
                ))
            reports.append(verify_team(profile, resolutions, team_role=team_role))
        return tuple(reports)
    except (discord.HTTPException, discord.ClientException) as exc:
        raise CommandUserError(localize(I18N.errors.discord_verification.members_unavailable)) from exc
