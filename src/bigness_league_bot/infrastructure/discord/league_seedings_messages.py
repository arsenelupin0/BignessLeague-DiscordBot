from __future__ import annotations

import discord

from bigness_league_bot.application.services.league_seedings import (
    LeagueDivisionSchedule, LeagueMatchday, LeagueSeedingsDestination, MATCHES_PER_MATCHDAY,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService

MESSAGE_LIMIT = 2000


def build_seedings_pages(
        schedule: LeagueDivisionSchedule, destination: LeagueSeedingsDestination, *,
        localizer: LocalizationService, locale: str | discord.Locale,
) -> tuple[str, ...]:
    """Present the saved calendar by matchday, with a link to its worksheet."""
    keys = I18N.messages.league_seedings
    heading = localizer.translate(
        keys.division_heading, locale=locale,
        division=schedule.division.value,
        emoji=localizer.translate(getattr(keys, schedule.division.name.lower() + "_emoji"), locale=locale),
    )
    heading += "\n" + localizer.translate(
        keys.destination, locale=locale,
        sheet_name=discord.utils.escape_markdown(destination.worksheet_title),
        sheet_url=destination.worksheet_url, ranges=", ".join(destination.ranges),
    )

    def matchday(day: LeagueMatchday) -> str:
        title = localizer.translate(keys.matchday_heading, locale=locale, number=day.number)
        matches = "\n".join(localizer.translate(
            keys.fixture, locale=locale, number=number,
            home=discord.utils.escape_markdown(match.home), away=discord.utils.escape_markdown(match.away),
        ) for number, match in enumerate(day.matches, 1))
        return f"{title}\n{matches}"

    def page(days: tuple[LeagueMatchday, ...]) -> str:
        label = localizer.translate(
            keys.matchdays, locale=locale, first=days[0].number,
            last=days[-1].number, matches=MATCHES_PER_MATCHDAY,
        )
        return f"{heading}\n{label}\n\n" + "\n\n".join(matchday(day) for day in days)

    # Spreadsheet names are never truncated to fit a Discord presentation.
    if any(len(page((day,))) > MESSAGE_LIMIT for day in schedule.matchdays):
        return (f"{heading}\n{localizer.translate(keys.summary_only, locale=locale)}",)

    pages: list[str] = []
    pending: tuple[LeagueMatchday, ...] = ()
    for day in schedule.matchdays:
        candidate = (*pending, day)
        if len(page(candidate)) > MESSAGE_LIMIT:
            pages.append(page(pending))
            pending = (day,)
        else:
            pending = candidate
    if pending:
        pages.append(page(pending))
    return tuple(pages)
