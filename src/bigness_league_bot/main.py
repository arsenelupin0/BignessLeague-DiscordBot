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

import logging

from bigness_league_bot.app.bootstrap import create_bot
from bigness_league_bot.app.logging import configure_logging
from bigness_league_bot.app.single_instance import (
    SingleInstanceLockError,
    create_single_instance_guard,
)
from bigness_league_bot.core.settings import Settings

LOGGER = logging.getLogger(__name__)


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings)
    try:
        with create_single_instance_guard(settings):
            bot = create_bot(settings)
            bot.run(settings.token, log_handler=None)
    except SingleInstanceLockError as exc:
        LOGGER.critical("BOT_SINGLE_INSTANCE_LOCK_FAILED details=%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
