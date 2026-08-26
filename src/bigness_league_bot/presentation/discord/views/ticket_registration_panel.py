#  Copyright (c) 2026. Bigness League.
#
#  Licensed under the GNU General Public License v3.0
#
#  https://www.gnu.org/licenses/gpl-3.0.html
#
#  Permissions of this strong copyleft license are conditioned on making available complete source code of licensed
#  works and modifications, which include larger works using a licensed work, under the same license. Copyright and
#  license notices must be preserved. Contributors provide an express grant of patent rights.

from __future__ import annotations

from bigness_league_bot.application.services.tickets import (
    REGISTRATION_TICKET_CATEGORIES,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N
from bigness_league_bot.presentation.discord.views.ticket_panel import TicketPanelView


class RegistrationTicketPanelView(TicketPanelView):
    categories = REGISTRATION_TICKET_CATEGORIES
    select_custom_id = "bigness_league:tickets:registration_category"
    select_placeholder = (
        I18N.messages.tickets.registration_panel.select_placeholder.default
    )
