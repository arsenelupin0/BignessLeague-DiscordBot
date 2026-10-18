from __future__ import annotations

import asyncio
import logging

from bigness_league_bot.application.services.match_replay_models import MatchReplayGame
from bigness_league_bot.application.services.match_replay_names import apply_replay_account_names
from bigness_league_bot.core.settings import Settings
from bigness_league_bot.infrastructure.replays.rrrocket import ReplayNameParserError, RrrocketNameReader

LOGGER = logging.getLogger(__name__)


def build_replay_name_reader(settings: Settings) -> RrrocketNameReader | None:
    if not settings.replay_name_parser_enabled:
        LOGGER.info("REPLAY_NAME_LOCAL_DISABLED")
        return None
    executable = settings.replay_name_parser_path
    if not executable.is_file():
        LOGGER.warning("REPLAY_NAME_LOCAL_FALLBACK reason=not_installed executable=%s", executable)
        return None
    return RrrocketNameReader(executable, timeout_seconds=settings.replay_name_parser_timeout_seconds)


async def recover_replay_game_names(
        game: MatchReplayGame, content: bytes, reader: RrrocketNameReader | None,
) -> MatchReplayGame:
    if reader is None:
        return game
    try:
        names = await asyncio.to_thread(reader.read_names, content)
    except ReplayNameParserError as exc:
        LOGGER.warning("REPLAY_NAME_LOCAL_FALLBACK replay_id=%s reason=%s details=%r",
                       game.replay_id, exc.reason, exc.details)
        return game
    enriched = apply_replay_account_names(game, names)
    local_count = 0
    for original_team, team in ((game.blue, enriched.blue), (game.orange, enriched.orange)):
        for original, player in zip(original_team.players, team.players):
            if player.name_source != "replay_header":
                LOGGER.info(
                    "REPLAY_NAME_LOCAL_FALLBACK replay_id=%s platform=%s platform_id=%s reason=no_unique_account",
                    game.replay_id, player.platform, player.platform_id)
                continue
            local_count += 1
            if original.name != player.name:
                LOGGER.info("REPLAY_NAME_LOCAL_RECOVERED replay_id=%s platform=%s ballchasing_name=%r local_name=%r",
                            game.replay_id, player.platform, original.name, player.name)
    LOGGER.info("REPLAY_NAME_LOCAL_RESULT replay_id=%s local_names=%s header_names=%s",
                game.replay_id, local_count, len(names))
    return enriched
