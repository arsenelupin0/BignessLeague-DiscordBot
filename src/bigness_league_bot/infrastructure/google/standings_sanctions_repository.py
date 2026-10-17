from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from bigness_league_bot.application.services.match_replays import MatchReplayDivision
from bigness_league_bot.application.services.match_standings import MatchStandingRow
from bigness_league_bot.application.services.standings_sanctions import (
    SanctionScope, StandingsSanction, add_sanction, annul_sanction, sanction_error, scope_team_names,
    team_key,
)
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.google.match_standings_repository import GoogleSheetsMatchStandingsRepository
from bigness_league_bot.infrastructure.google.sanctions_sheet import (
    SanctionsSheetStore, ledger_updates, serialized_standings_write,
)


@dataclass(frozen=True, slots=True)
class SanctionChangeResult:
    sanction: StandingsSanction
    standings: tuple[MatchStandingRow, ...]


class GoogleSheetsStandingsSanctionsRepository:
    def __init__(self, settings: Settings) -> None:
        self.standings = GoogleSheetsMatchStandingsRepository(settings)
        self.store = SanctionsSheetStore(self.standings.config)

    async def add(self, division: MatchReplayDivision, **kwargs) -> SanctionChangeResult:
        return await asyncio.to_thread(self.add_sync, division, **kwargs)

    async def annul(self, division: MatchReplayDivision, **kwargs) -> SanctionChangeResult:
        return await asyncio.to_thread(self.annul_sync, division, **kwargs)

    async def list(self, division: MatchReplayDivision) -> tuple[SanctionScope, tuple[StandingsSanction, ...]]:
        return await asyncio.to_thread(self.list_sync, division)

    @serialized_standings_write
    def add_sync(
            self, division: MatchReplayDivision, *, identifier: str, team_name: str, points: int,
            reason: str, kind: str, matchday: int | None, match_number: int | None,
            actor: str, rosters: tuple[tuple[str, str], ...],
    ) -> SanctionChangeResult:
        service = self.standings.client.build_service(read_only=False)
        worksheet = self.standings.resolve_standings_worksheet(service, division=division)
        scope = SanctionScope.from_worksheet(worksheet)
        if scope.division.casefold() != division.value:
            raise sanction_error("scope", sheet_name=worksheet)
        names = scope_team_names(scope, rosters)
        canonical_names = {team_key(name): name for name in names}
        if team_key(team_name) not in canonical_names:
            raise sanction_error("unknown_team", team=team_name)
        ledger = self.store.read(service)
        # An interaction retry must never create a second deduction or reset its audit timestamp.
        previous = next((record for record in ledger.records if record.identifier == identifier), None)
        sanction = StandingsSanction(
            identifier, worksheet, scope.season, scope.division, canonical_names[team_key(team_name)],
            points, reason.strip(), kind, matchday, match_number, "ACTIVA",
            previous.created_at if previous else datetime.now(timezone.utc).isoformat(timespec="seconds"), actor,
        )
        records = add_sanction(ledger.records, sanction)
        rows = self.standings.standings_gateway.refresh_standings_from_grid(
            service, worksheet_name=worksheet, team_names=names, sanctions=records,
            extra_updates=ledger_updates(ledger, records),
        )
        return SanctionChangeResult(sanction, rows)

    @serialized_standings_write
    def annul_sync(
            self, division: MatchReplayDivision, *, identifier: str, actor: str, reason: str,
            rosters: tuple[tuple[str, str], ...],
    ) -> SanctionChangeResult:
        service = self.standings.client.build_service(read_only=False)
        worksheet = self.standings.resolve_standings_worksheet(service, division=division)
        scope = SanctionScope.from_worksheet(worksheet)
        names = scope_team_names(scope, rosters)
        ledger = self.store.read(service)
        if not any(record.identifier == identifier and record.belongs_to(scope) for record in ledger.records):
            raise sanction_error("not_found", identifier=identifier)
        records = annul_sanction(ledger.records, identifier,
                                 at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 by=actor, reason=reason)
        rows = self.standings.standings_gateway.refresh_standings_from_grid(
            service, worksheet_name=worksheet, team_names=names, sanctions=records,
            extra_updates=ledger_updates(ledger, records),
        )
        return SanctionChangeResult(next(record for record in records if record.identifier == identifier), rows)

    @serialized_standings_write
    def list_sync(self, division: MatchReplayDivision) -> tuple[SanctionScope, tuple[StandingsSanction, ...]]:
        service = self.standings.client.build_service(read_only=True)
        worksheet = self.standings.resolve_standings_worksheet(service, division=division)
        scope = SanctionScope.from_worksheet(worksheet)
        records = self.store.read(service).records
        return scope, tuple(record for record in records if record.belongs_to(scope))
