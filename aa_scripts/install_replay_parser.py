"""Prepare the parser bundled with the project; never download executable code."""
from __future__ import annotations

import argparse
from pathlib import Path

from bigness_league_bot.infrastructure.replays.runtime import (
    BOXCARS_VERSION, VERSION, ensure_bundled_runtime, executable_name,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara rrrocket desde los paquetes incluidos en el repositorio.")
    parser.add_argument("--destination", type=Path,
                        default=Path(__file__).resolve().parents[1] / "aa_var/tools/rrrocket")
    parser.add_argument("--force", action="store_true", help="Reemplaza la copia local con la versión incluida.")
    args = parser.parse_args()
    target = ensure_bundled_runtime(args.destination / executable_name(), force=args.force)
    print(f"Preparado rrrocket {VERSION} / Boxcars {BOXCARS_VERSION}: {target}")


if __name__ == "__main__":
    main()
