from __future__ import annotations

import unittest

from bigness_league_bot.infrastructure.google.team_sheets.cells import _build_sheet_grid


class SheetCellLinkTests(unittest.TestCase):
    def parse(self, **fields: object):
        sheet = {"data": [{"rowData": [{"values": [{"formattedValue": "Profit", **fields}]}]}]}
        return _build_sheet_grid(sheet)[0][0]

    def test_link_on_title_text_is_read_without_hyperlink_field(self) -> None:
        cell = self.parse(textFormatRuns=[
            {"startIndex": 0, "format": {"link": {"uri": "https://cdn.example.com/Profit.png"}}},
            {"startIndex": 3, "format": {"bold": True}},
        ])
        self.assertEqual(cell.value, "Profit")
        self.assertEqual(cell.hyperlink, "https://cdn.example.com/Profit.png")

    def test_cell_format_links_are_read(self) -> None:
        for field in ("userEnteredFormat", "effectiveFormat"):
            with self.subTest(field=field):
                cell = self.parse(**{field: {"textFormat": {"link": {"uri": " https://example.com/logo.png "}}}})
                self.assertEqual(cell.hyperlink, "https://example.com/logo.png")

    def test_repeated_destination_across_text_runs_is_unambiguous(self) -> None:
        link = {"uri": "https://example.com/logo.png"}
        cell = self.parse(userEnteredFormat={"textFormat": {"link": link}}, textFormatRuns=[
            {"startIndex": 0, "format": {"link": link}},
            {"startIndex": 2, "format": {"link": link}},
        ])
        self.assertEqual(cell.hyperlink, link["uri"])

    def test_distinct_destinations_are_not_silently_selected(self) -> None:
        with self.assertLogs("bigness_league_bot.activity", level="WARNING") as logs:
            cell = self.parse(textFormatRuns=[
                {"startIndex": 0, "format": {"link": {"uri": "https://example.com/old.png"}}},
                {"startIndex": 3, "format": {"link": {"uri": "https://example.com/new.png"}}},
            ])
        self.assertIsNone(cell.hyperlink)
        self.assertIn("SHEET_CELL_HYPERLINK_AMBIGUOUS", logs.output[0])

    def test_text_link_overrides_cell_link_when_it_covers_the_entire_title(self) -> None:
        cell = self.parse(userEnteredFormat={"textFormat": {"link": {"uri": "https://example.com/old.png"}}},
                          textFormatRuns=[{"startIndex": 0, "format": {
                              "link": {"uri": "https://example.com/new.png"},
                          }}])
        self.assertEqual(cell.hyperlink, "https://example.com/new.png")

    def test_links_on_empty_trailing_runs_do_not_make_the_title_ambiguous(self) -> None:
        cell = self.parse(textFormatRuns=[
            {"startIndex": 0, "format": {"link": {"uri": "https://example.com/new.png"}}},
            {"startIndex": 6, "format": {"link": {"uri": "https://example.com/old.png"}}},
        ])
        self.assertEqual(cell.hyperlink, "https://example.com/new.png")

    def test_existing_hyperlink_and_formula_take_precedence(self) -> None:
        fields = {"userEnteredFormat": {"textFormat": {"link": {"uri": "https://example.com/old.png"}}}}
        self.assertEqual(self.parse(hyperlink="https://example.com/new.png", **fields).hyperlink,
                         "https://example.com/new.png")
        self.assertEqual(self.parse(userEnteredValue={
            "formulaValue": '=HYPERLINK("https://example.com/new.png";"Profit")',
        }, **fields).hyperlink, "https://example.com/new.png")

    def test_unlinked_and_malformed_formats_do_not_invent_a_link(self) -> None:
        for fields in ({}, {"textFormatRuns": None}, {"userEnteredFormat": "bad"},
                       {"textFormatRuns": [None, {"format": {"link": {"uri": 123}}}]}):
            with self.subTest(fields=fields):
                self.assertIsNone(self.parse(**fields).hyperlink)
