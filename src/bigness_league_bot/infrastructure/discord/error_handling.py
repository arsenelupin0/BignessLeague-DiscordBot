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

from bigness_league_bot.infrastructure.discord.channel_management import (
    ChannelManagementError,
)


@dataclass(frozen=True, slots=True)
class AppCommandErrorDetails:
    user_message: str
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

    if isinstance(original_error, ChannelManagementError):
        return AppCommandErrorDetails(
            user_message=str(original_error),
            log_level=logging.WARNING,
            log_code="SLASH_COMMAND_REJECTED",
            expected=True,
        )

    if isinstance(original_error, app_commands.CheckFailure):
        return AppCommandErrorDetails(
            user_message="No tienes permisos para ejecutar este comando.",
            log_level=logging.WARNING,
            log_code="SLASH_COMMAND_FORBIDDEN",
            expected=True,
        )

    if isinstance(original_error, app_commands.BotMissingPermissions):
        return AppCommandErrorDetails(
            user_message="El bot necesita permisos suficientes para gestionar el canal.",
            log_level=logging.ERROR,
            log_code="SLASH_COMMAND_BOT_MISSING_PERMISSIONS",
            expected=False,
        )

    if isinstance(original_error, discord.Forbidden):
        return AppCommandErrorDetails(
            user_message="Discord ha rechazado la accion. Revisa los permisos del bot.",
            log_level=logging.ERROR,
            log_code="SLASH_COMMAND_DISCORD_FORBIDDEN",
            expected=False,
        )

    if isinstance(original_error, discord.HTTPException):
        return AppCommandErrorDetails(
            user_message="Discord ha devuelto un error al actualizar el canal.",
            log_level=logging.ERROR,
            log_code="SLASH_COMMAND_HTTP_ERROR",
            expected=False,
        )

    return AppCommandErrorDetails(
        user_message="Ha ocurrido un error inesperado al procesar el comando.",
        log_level=logging.ERROR,
        log_code="SLASH_COMMAND_ERROR",
        expected=False,
        include_traceback=True,
    )
