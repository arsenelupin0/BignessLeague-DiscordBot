"""Inspect the same local names consumed by the Discord replay workflow."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from bigness_league_bot.infrastructure.replays.rrrocket import ReplayNameParserError, RrrocketNameReader


def main() -> None:
    parser = argparse.ArgumentParser(description="Lee nombres Unicode e identidades de archivos .replay.")
    parser.add_argument("replays", type=Path, nargs="+")
    parser.add_argument("--parser-path", type=Path,
                        default=Path(__file__).resolve().parents[1] / "aa_var/tools/rrrocket"
                                / ("rrrocket.exe" if os.name == "nt" else "rrrocket"))
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    reader = RrrocketNameReader(args.parser_path)
    output = []
    failed = False
    for path in args.replays:
        try:
            content = path.read_bytes()
            names = reader.read_names(content)
            output.append({"file": path.name, "sha256": hashlib.sha256(content).hexdigest(),
                           "players": [{"platform": name.platform, "platform_id": name.platform_id,
                                        "name": name.name} for name in names]})
        except (OSError, ReplayNameParserError) as exc:
            failed = True
            output.append({"file": path.name, "error": str(exc)})
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
