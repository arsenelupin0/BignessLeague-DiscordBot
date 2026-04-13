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
from dataclasses import dataclass

import discord
from discord import app_commands

from bigness_league_bot.core.errors import CommandUserError
from bigness_league_bot.core.localization import LocalizedText, localize
from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelManagementError,
)
from bigness_league_bot.infrastructure.i18n.keys import I18N


@dataclass(frozen=True, slots=True)
class AppCommandErrorDetails:
    user_message: LocalizedText
    log_level: int
    log_code: str
    expected: bool
    include_traceback: bool = False


def unwrap_app_command_error(error: app_commands.AppCommandError) -> BaseException:
    if isinstance(error, app_commands.CommandInvokeError):
        return error.original
    return error


def classify_app_command_error(
        error: app_commands.AppCommandError,
) -> AppCommandErrorDetails:
    original_error = unwrap_app_command_error(error)

    if isinstance(original_error, (CommandUserError, ChannelManagementError)):
        return AppCommandErrorDetails(
            user_message=original_error.message,
            log_level=logging.WARNING,
            log_code="SLASH_COMMAND_REJECTED",
            expected=True,
        )

    if isinstance(original_error, app_commands.CheckFailure):
        return AppCommandErrorDetails(
            user_message=localize(I18N.errors.slash.forbidden),
            log_level=logging.WARNING,
            log_code="SLASH_COMMAND_FORBIDDEN",
            expected=True,
        )

    if isinstance(original_error, app_commands.BotMissingPermissions):
        return AppCommandErrorDetails(
            user_message=localize(I18N.errors.slash.bot_missing_permissions),
            log_level=logging.ERROR,
            log_code="SLASH_COMMAND_BOT_MISSING_PERMISSIONS",
            expected=False,
        )

    if isinstance(original_error, discord.Forbidden):
        return AppCommandErrorDetails(
            user_message=localize(I18N.errors.slash.discord_forbidden),
            log_level=logging.ERROR,
            log_code="SLASH_COMMAND_DISCORD_FORBIDDEN",
            expected=False,
        )

    if isinstance(original_error, discord.HTTPException):
        return AppCommandErrorDetails(
            user_message=localize(I18N.errors.slash.http_error),
            log_level=logging.ERROR,
            log_code="SLASH_COMMAND_HTTP_ERROR",
            expected=False,
        )

    return AppCommandErrorDetails(
        user_message=localize(I18N.errors.slash.unexpected),
        log_level=logging.ERROR,
        log_code="SLASH_COMMAND_ERROR",
        expected=False,
        include_traceback=True,
    )
