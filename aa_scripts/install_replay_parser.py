"""Install a pinned official rrrocket binary, without modifying Python packages."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.11.8"
BOXCARS_VERSION = "0.13.0"
RELEASE = f"https://github.com/nickbabcock/rrrocket/releases/download/v{VERSION}"
ASSETS = {
    ("Windows", "x86_64"): ("x86_64-pc-windows-msvc.zip",
                            "bc652d48b382f25b7ff1da65942b6800366501ed1c2eb1d440058bb1821a7869"),
    ("Linux", "x86_64"): ("x86_64-unknown-linux-musl.tar.gz",
                          "c78b674728de915fa1a76ea7fec16d57df7f9371fbbc1062f4f50b44999f530f"),
    ("Darwin", "x86_64"): ("x86_64-apple-darwin.tar.gz",
                           "2940f4e54c80967c8d7d2d2d8775a23cc89408a05c007bb9986fbd4b720f63fd"),
    ("Darwin", "aarch64"): ("aarch64-apple-darwin.tar.gz",
                            "1408f9dc0f3741e7755f8e19f65b8d75e039394d8b7fa1f8912c6e292acf4723"),
}
LICENSE_SHA256 = "91276db973f25602d1aa43491f59cbc84cb88e6f151e1d0cc82a755563ce0195"
DEFAULT_DESTINATION = Path(__file__).resolve().parents[1] / "aa_var/tools/rrrocket"


def download_verified(url: str, expected_sha256: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "BignessLeague-replay-parser-installer"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("La descarga no coincide con el SHA256 fijado.")
    return content


def executable_from_archive(content: bytes, *, windows: bool) -> bytes:
    name = "rrrocket.exe" if windows else "rrrocket"
    if windows:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            matches = [entry for entry in archive.infolist() if
                       Path(entry.filename).name == name and not entry.is_dir()]
            if len(matches) != 1 or matches[0].file_size > 16 * 1024 * 1024:
                raise ValueError("El paquete no contiene un ejecutable único válido.")
            return archive.read(matches[0])
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        matches = [entry for entry in archive.getmembers() if Path(entry.name).name == name and entry.isfile()]
        if len(matches) != 1 or matches[0].size > 16 * 1024 * 1024:
            raise ValueError("El paquete no contiene un ejecutable único válido.")
        source = archive.extractfile(matches[0])
        assert source is not None
        return source.read()


def main() -> None:
    parser = argparse.ArgumentParser(description="Instala rrrocket con versión y SHA256 fijados.")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    system = platform.system()
    if (system, machine) not in ASSETS:
        parser.error(
            f"Plataforma sin binario fijado: {system}/{machine}. Configura un ejecutable compatible manualmente.")
    suffix, digest = ASSETS[system, machine]
    asset = f"rrrocket-{VERSION}-{suffix}"
    content = download_verified(f"{RELEASE}/{asset}", digest)
    license_content = download_verified(
        f"https://raw.githubusercontent.com/nickbabcock/rrrocket/v{VERSION}/LICENSE.txt", LICENSE_SHA256,
    )
    executable = executable_from_archive(content, windows=system == "Windows")
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / ("rrrocket.exe" if system == "Windows" else "rrrocket")
    temporary = target.with_suffix(".download")
    temporary.write_bytes(executable)
    if os.name != "nt":
        temporary.chmod(0o755)
    temporary.replace(target)
    (destination / "LICENSE.txt").write_bytes(license_content)
    (destination / "manifest.json").write_text(json.dumps({
        "version": VERSION, "boxcars_version": BOXCARS_VERSION,
        "source": f"{RELEASE}/{asset}", "archive_sha256": digest,
        "executable_sha256": hashlib.sha256(executable).hexdigest(),
    }, indent=2), encoding="utf-8")
    print(f"Instalado rrrocket {VERSION} / Boxcars {BOXCARS_VERSION}: {target}")


if __name__ == "__main__":
    main()
