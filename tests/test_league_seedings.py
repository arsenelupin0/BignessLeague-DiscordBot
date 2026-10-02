from __future__ import annotations

import random
import unittest
from collections import Counter
from dataclasses import replace
from itertools import combinations
from pathlib import Path

from bigness_league_bot.application.services.league_seedings import (
    LeagueTeam, LeagueSeedingsDestination, generate_league_seedings, league_fixture_rows,
)
from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.infrastructure.discord.league_seedings_messages import (
    build_seedings_pages,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.infrastructure.i18n.service import LocalizationService


def league_teams() -> tuple[LeagueTeam, ...]:
    return tuple(LeagueTeam(f"{division} Division S4", f"{division} Equipo {index}")
                 for division in ("Gold", "Silver") for index in range(1, 9))


def localizer() -> LocalizationService:
    return LocalizationService.from_directory(
        directory=Path(__file__).resolve().parents[1] / "aa_resources/locales", default_locale="es-ES",
    )


class LeagueSeedingsTests(unittest.TestCase):
    def test_round_robin_invariants_over_many_draws(self) -> None:
        for seed in range(100):
            schedules = generate_league_seedings(league_teams(), rng=random.Random(seed))
            self.assertEqual([s.division.value for s in schedules], ["Gold Division", "Silver Division"])
            for schedule in schedules:
                expected = {t.team_name for t in league_teams() if t.worksheet_title == schedule.worksheet_title}
                appearances, home_counts = Counter(), Counter()
                pairs = []
                self.assertEqual([day.number for day in schedule.matchdays], list(range(1, 8)))
                for day in schedule.matchdays:
                    self.assertEqual(len(day.matches), 4)
                    self.assertEqual(Counter(name for match in day.matches for name in (match.home, match.away)),
                                     Counter({name: 1 for name in expected}))
                    for match in day.matches:
                        self.assertNotEqual(match.home, match.away)
                        appearances.update((match.home, match.away))
                        home_counts.update((match.home,))
                        pairs.append(frozenset((match.home, match.away)))
                self.assertEqual(len(pairs), 28)
                self.assertEqual(set(pairs), {frozenset(pair) for pair in combinations(expected, 2)})
                self.assertEqual(appearances, Counter({name: 7 for name in expected}))
                self.assertEqual(sorted(home_counts.values()), [3, 3, 3, 3, 4, 4, 4, 4])

    def test_randomness_is_injectable_and_inputs_are_unchanged(self) -> None:
        teams = league_teams()
        first = generate_league_seedings(iter(teams), rng=random.Random(10))
        self.assertEqual(first, generate_league_seedings(teams, rng=random.Random(10)))
        self.assertNotEqual(first, generate_league_seedings(teams, rng=random.Random(11)))
        self.assertEqual(teams, league_teams())
        self.assertEqual(len(generate_league_seedings(teams)), 2)

    def assert_rejected(self, teams, key, **params) -> None:
        with self.assertRaises(CommandUserError) as caught:
            generate_league_seedings(teams)
        self.assertEqual(caught.exception.message.key, f"errors.league_seedings.{key}")
        for param, value in params.items():
            self.assertEqual(caught.exception.message.params[param], value)
        for locale in ("es-ES", "en-US"):
            text = localizer().render(caught.exception.message, locale=locale)
            self.assertNotIn("errors.league_seedings", text)
            self.assertNotIn("{", text)

    def test_missing_division_and_wrong_team_counts_are_rejected(self) -> None:
        teams = league_teams()
        for selected, actual in (((), 0), (teams[1:], 7), (teams + (LeagueTeam("Gold Division S4", "Extra"),), 9)):
            self.assert_rejected(selected, "team_count", division="Gold Division", actual=actual, expected=8)
        self.assert_rejected(teams[:8], "team_count", division="Silver Division", actual=0)

    def test_case_spacing_and_unicode_duplicate_names_are_rejected(self) -> None:
        for duplicate in ("gold equipo 1", " GOLD  EQUIPO  1 ", "Ｇｏｌｄ Equipo 1"):
            teams = list(league_teams())
            teams[1] = replace(teams[1], team_name=duplicate)
            self.assert_rejected(teams, "duplicate_team", division="Gold Division")

    def test_unexportable_names_are_rejected(self) -> None:
        for name in ("", " ", "A\tB", "A\nB", "A\rB", "A\x00B", "A\u2028B", "A\u2029B"):
            teams = list(league_teams())
            teams[0] = replace(teams[0], team_name=name)
            self.assert_rejected(teams, "invalid_team_name", division="Gold Division")

    def test_other_competitions_are_ignored_and_division_normalization_is_reused(self) -> None:
        teams = tuple(replace(t, worksheet_title=t.worksheet_title.upper()) for t in league_teams())
        teams += (LeagueTeam("Bigness Cup Junior", "Otro equipo"),)
        self.assertEqual(len(generate_league_seedings(teams)), 2)
        no_season = tuple(replace(t, worksheet_title=t.worksheet_title.removesuffix(" S4")) for t in league_teams())
        self.assertEqual(len(generate_league_seedings(no_season)), 2)

    def test_ambiguous_divisions_and_mixed_seasons_are_rejected(self) -> None:
        teams = league_teams()
        self.assert_rejected(teams + (LeagueTeam("Gold Division S3", "Anterior"),), "ambiguous_division")
        self.assert_rejected(tuple(replace(t, worksheet_title="Silver Division S3") if index >= 8 else t
                                   for index, t in enumerate(teams)), "season_mismatch")

    def test_environment_worksheet_suffixes_preserve_divisions_and_team_names(self) -> None:
        for suffix in ("TEST", "DEV", "DEVELOPMENT"):
            with self.subTest(suffix=suffix):
                teams = tuple(replace(t, worksheet_title=t.worksheet_title.upper() + f" {suffix}")
                              for t in league_teams())
                schedules = generate_league_seedings(teams, rng=random.Random(1))
                for schedule in schedules:
                    expected = {t.team_name for t in teams if t.worksheet_title == schedule.worksheet_title}
                    matches = [match for day in schedule.matchdays for match in day.matches]
                    self.assertEqual(len(matches), 28)
                    self.assertEqual({frozenset((match.home, match.away)) for match in matches},
                                     {frozenset(pair) for pair in combinations(expected, 2)})
                    self.assertEqual(Counter(name for match in matches for name in (match.home, match.away)),
                                     Counter({name: 7 for name in expected}))
                    self.assertTrue(schedule.worksheet_title.endswith(suffix))

    def test_environment_suffix_supports_accents_case_and_spacing(self) -> None:
        teams = tuple(replace(t, worksheet_title=t.worksheet_title.replace("Division", "DIVISIÓN")
                                                 + "  tEsT  ") for t in league_teams())
        schedules = generate_league_seedings(teams)
        self.assertEqual([s.worksheet_title for s in schedules],
                         [teams[0].worksheet_title, teams[8].worksheet_title])

    def test_environment_suffix_does_not_hide_mixed_seasons_or_ambiguous_sheets(self) -> None:
        teams = tuple(replace(t, worksheet_title=t.worksheet_title + " TEST") for t in league_teams())
        self.assert_rejected(tuple(replace(t, worksheet_title="Silver Division S3 TEST")
                                   if index >= 8 else t for index, t in enumerate(teams)), "season_mismatch")
        self.assert_rejected(teams + (LeagueTeam("Gold Division S4", "Oficial"),), "ambiguous_division")

    def test_unrecognized_worksheet_suffix_does_not_select_another_competition(self) -> None:
        teams = tuple(replace(t, worksheet_title=t.worksheet_title + " PLAYOFFS") for t in league_teams())
        self.assert_rejected(teams, "team_count", division="Gold Division", actual=0)


class LeagueSeedingsPresentationTests(unittest.TestCase):
    def schedule(self, name_length=0):
        teams = tuple(replace(t, team_name=t.team_name + "x" * name_length) for t in league_teams())
        return generate_league_seedings(teams, rng=random.Random(1))[0]

    def destination(self, schedule):
        return LeagueSeedingsDestination(schedule.division, "Clasificación Gold S4 TEST",
                                         "https://docs.google.com/spreadsheets/d/test/edit#gid=1", ("B20:D47",))

    def pages(self, schedule, locale="es-ES"):
        return build_seedings_pages(schedule, self.destination(schedule), localizer=localizer(), locale=locale)

    def test_28_fixture_rows_use_the_existing_upload_coordinates(self) -> None:
        schedule = self.schedule()
        rows = league_fixture_rows(schedule)
        self.assertEqual(len(rows), 28)
        self.assertEqual([row.row_number for row in rows], list(range(20, 48)))
        for row, match in zip(rows, (m for day in schedule.matchdays for m in day.matches)):
            self.assertEqual((row.home, row.away), (match.home, match.away))

    def test_saved_matchdays_are_presented_with_worksheet_links_in_both_locales(self) -> None:
        schedule = self.schedule()
        for locale in ("es-ES", "en-US"):
            pages = self.pages(schedule, locale)
            content = "\n".join(pages)
            self.assertIn("Gold Division", content)
            self.assertIn("B20:D47", content)
            self.assertIn(self.destination(schedule).worksheet_url, content)
            self.assertNotIn("```text", content)
            for name in {row.home for row in league_fixture_rows(schedule)}:
                self.assertEqual(content.count(name), 7)
            for page in pages:
                self.assertLessEqual(len(page), 2000)
            self.assertLessEqual(len(localizer().translate(I18N.messages.league_seedings.overview, locale=locale)),
                                 2000)

    def test_long_names_paginate_only_between_complete_matchdays(self) -> None:
        schedule = self.schedule(name_length=90)
        for locale in ("es-ES", "en-US"):
            pages = self.pages(schedule, locale)
            self.assertGreater(len(pages), 1)
            for page in pages:
                self.assertLessEqual(len(page), 2000)
                self.assertEqual(page.count("**P1**"), page.count("**P4**"))
                self.assertEqual(page.count("**P1**"), page.count("**P2**"))
                self.assertEqual(page.count("**P1**"), page.count("**P3**"))
            self.assertEqual(sum(page.count("**P1**") for page in pages), 7)

    def test_extreme_names_fall_back_to_the_saved_calendar_link(self) -> None:
        name = "L" * 2500
        teams = list(league_teams())
        teams[0] = replace(teams[0], team_name=name)
        schedule = generate_league_seedings(teams)[0]
        pages = self.pages(schedule)
        self.assertEqual(len(pages), 1)
        self.assertIn(self.destination(schedule).worksheet_url, pages[0])
        self.assertLessEqual(len(pages[0]), 2000)
        self.assertEqual(sum(name in (row.home, row.away) for row in league_fixture_rows(schedule)), 7)

    def test_names_with_accents_emoji_and_spaces_are_preserved(self) -> None:
        teams = list(league_teams())
        name = "  Águilas | 🇪🇸 `RL`  "
        teams[0] = replace(teams[0], team_name=name)
        schedule = generate_league_seedings(teams)[0]
        self.assertEqual(sum(name in (row.home, row.away) for row in league_fixture_rows(schedule)), 7)
        escaped_name = name.replace("|", "\\|").replace("`", "\\`")
        self.assertEqual("\n".join(self.pages(schedule)).count(escaped_name), 7)


if __name__ == "__main__":
    unittest.main()
