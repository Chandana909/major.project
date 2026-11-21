"""Everything AuditIQ needs before its live run, fetched once, then the live run itself (scripts/live.py).

    python scripts/bootstrap.py                   Java, Node.js and Kafka if missing; stream the final ledger
    python scripts/bootstrap.py --huge            the same with the 500,000-invoice ledger (data_archives/)
    python scripts/bootstrap.py --limit 2000      any option of scripts/live.py is passed on
    python scripts/bootstrap.py stop | reset      stop the Kafka broker / delete every run's topics

`run.sh` in the repository's root calls this file after it has made the Python environment. What is missing is
downloaded into `.tools/` of the project (never system-wide) and checked before it is used:

    Java 17       when no Java 17 or later is on PATH or in JAVA_HOME: the Eclipse Temurin runtime from
                  api.adoptium.net, checked against the SHA-256 the same API publishes
    Node.js 20    when no Node 20 or later is on PATH: the release from nodejs.org, checked against its
                  SHASUMS256.txt; needed once, to build the web application
    Kafka 4.3.2   when the local broker is not set up: the release from downloads.apache.org (or the Apache
                  archive), checked against its .sha512, then unpacked and formatted by scripts/kafka_local.py
    huge ledger   with --huge: data_archives/huge_seed_606.tar.xz unpacked into data_huge/ (2 GB)

Only the standard library is used, so this runs before any package is installed.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
NODE_VERSION = "20.18.1"
KAFKA_VERSION, SCALA_VERSION = "4.3.2", "2.13"
HUGE_ARCHIVE = ROOT / "data_archives" / "huge_seed_606.tar.xz"
HUGE_LEDGER = ROOT / "data_huge" / "huge_seed_606"
AGENT = {"User-Agent": "auditiq-bootstrap"}

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kafka_local  # noqa: E402  (the script beside this one)


def say(text: str) -> None:
    print(f"[auditiq] {text}", flush=True)


def system() -> tuple[str, str]:
    """(windows | mac | linux, x64 | aarch64)."""
    name = {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    return name, "aarch64" if machine in ("arm64", "aarch64") else "x64"


def fetch(url: str, dest: Path) -> Path:
    """Download to dest (through a .part file, so that an interrupted download is not taken for a whole one)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    say(f"downloading {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=60) as reply, part.open("wb") as out:
        total, done, shown = int(reply.headers.get("Content-Length") or 0), 0, -1
        while chunk := reply.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            percent = int(done * 100 / total) if total else -1
            if total and percent // 10 != shown:
                shown = percent // 10
                print(f"    {done / 1e6:7.1f} of {total / 1e6:.1f} MB", flush=True)
    part.replace(dest)
    return dest


def text_of(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=60) as reply:
        return reply.read().decode("utf-8", "replace")


def checksum(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, algorithm: str, expected: str) -> None:
    found = checksum(path, algorithm)
    if found.lower() != expected.lower():
        path.unlink(missing_ok=True)
        raise SystemExit(f"{path.name}: the {algorithm} does not match the published one; the download was removed")
    say(f"{path.name}: {algorithm} verified")


def unpack(archive: Path, into: Path) -> Path:
    """Unpack a .tar.gz, .tar.xz or .zip into a new folder; returns the folder."""
    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            root = into.resolve()
            for member in z.namelist():
                if root not in (into / member).resolve().parents and (into / member).resolve() != root:
                    raise SystemExit(f"refusing to unpack {member!r}: outside the folder")
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(into)
    return into


# ------------------------------------------------------------------ Java
def java_major(executable: str) -> int:
    try:
        done = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=30)
    except OSError:
        return 0
    found = re.search(r'version "(\d+)(?:\.(\d+))?', done.stderr + done.stdout)
    if not found:
        return 0
    major = int(found.group(1))
    return int(found.group(2) or 0) if major == 1 else major       # "1.8.0" is Java 8


def ensure_java() -> None:
    home = os.environ.get("JAVA_HOME")
    candidates = ([str(Path(home) / "bin" / "java")] if home else []) + ([shutil.which("java")] if shutil.which("java") else [])
    for java in candidates:
        if java_major(java) >= 17:
            say(f"Java {java_major(java)} found")
            return
    local = next(iter(sorted((TOOLS / "java").glob("**/bin/java*"))), None) if (TOOLS / "java").exists() else None
    if local is None:
        name, arch = system()
        assets = json.loads(text_of(f"https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture={arch}"
                                    f"&image_type=jre&os={name}&vendor=eclipse"))
        package = assets[0]["binary"]["package"]
        archive = fetch(package["link"], TOOLS / "downloads" / package["name"])
        verify(archive, "sha256", package["checksum"])
        unpack(archive, TOOLS / "java")
        local = next(iter(sorted((TOOLS / "java").glob("**/bin/java*"))))
    java_home = local.parent.parent
    os.environ["JAVA_HOME"] = str(java_home)
    os.environ["PATH"] = str(java_home / "bin") + os.pathsep + os.environ.get("PATH", "")
    say(f"Java from {java_home}")


# ------------------------------------------------------------------ Node.js
def node_major() -> int:
    node = shutil.which("node")
    if not node or not shutil.which("npm"):
        return 0
    try:
        done = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30)
        return int(done.stdout.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError):
        return 0


def ensure_node() -> None:
    if (ROOT / "frontend" / "dist" / "index.html").exists():
        say("web application already built")
        return
    if node_major() >= 20:
        say(f"Node.js {node_major()} found")
        return
    name, arch = system()
    plat = {"windows": "win", "mac": "darwin", "linux": "linux"}[name]
    arch = "arm64" if arch == "aarch64" else "x64"
    ext = "zip" if plat == "win" else "tar.gz" if plat == "darwin" else "tar.xz"
    stem = f"node-v{NODE_VERSION}-{plat}-{arch}"
    folder = TOOLS / "node" / stem
    if not folder.exists():
        base = f"https://nodejs.org/dist/v{NODE_VERSION}"
        archive = fetch(f"{base}/{stem}.{ext}", TOOLS / "downloads" / f"{stem}.{ext}")
        sums = {line.split()[1]: line.split()[0] for line in text_of(f"{base}/SHASUMS256.txt").splitlines() if line.strip()}
        verify(archive, "sha256", sums[f"{stem}.{ext}"])
        unpack(archive, TOOLS / "node")
    bin_dir = folder if plat == "win" else folder / "bin"
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    say(f"Node.js {NODE_VERSION} from {folder}")


# ------------------------------------------------------------------ Kafka
def ensure_kafka() -> None:
    if kafka_local.CONFIG.exists() and (kafka_local.HOME / "libs").exists():
        say(f"Kafka found in {kafka_local.HOME}")
        return
    if kafka_local.HOME.exists():
        raise SystemExit(f"{kafka_local.HOME} exists but is not a usable Kafka: remove it and run again")
    name = f"kafka_{SCALA_VERSION}-{KAFKA_VERSION}.tgz"
    archive = TOOLS / "downloads" / name
    for base in (f"https://downloads.apache.org/kafka/{KAFKA_VERSION}",
                 f"https://archive.apache.org/dist/kafka/{KAFKA_VERSION}"):
        try:
            published = text_of(f"{base}/{name}.sha512")
            if not archive.exists():
                fetch(f"{base}/{name}", archive)
            break
        except OSError as error:
            say(f"{base}: {error}; trying the next mirror")
    else:
        raise SystemExit("Kafka could not be downloaded; check the internet connection")
    expected = re.sub(r"\s+", "", published.split(":", 1)[1] if ":" in published else published.split()[0])
    verify(archive, "sha512", expected)
    kafka_local.init(archive)


# ------------------------------------------------------------------ the huge ledger
def ensure_huge() -> Path:
    if (HUGE_LEDGER / "invoices.csv").exists():
        say(f"huge ledger found in {HUGE_LEDGER}")
        return HUGE_LEDGER
    if not HUGE_ARCHIVE.exists():
        raise SystemExit(f"{HUGE_ARCHIVE} is missing; it is part of the repository")
    say("unpacking the 500,000-invoice ledger (52 MB to about 2 GB; a minute or two)")
    HUGE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(HUGE_ARCHIVE) as t:
        t.extractall(HUGE_LEDGER.parent, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(HUGE_LEDGER.parent)
    return HUGE_LEDGER


def main(argv: list[str]) -> int:
    args = list(argv)
    huge = "--huge" in args
    args = [a for a in args if a != "--huge"]
    action = args[0] if args and args[0] in ("stop", "reset") else None
    if action is None:
        ensure_java()
        ensure_kafka()
        ensure_node()
        if huge:
            if "--ledger" in args:
                raise SystemExit("--huge and --ledger choose the ledger twice; use one of them")
            args += ["--ledger", str(ensure_huge())]
            say("streaming 500,000 invoices through Kafka takes about an hour on a laptop; the web application opens "
                "at once and fills as the audit goes")
    else:
        ensure_java()
    return subprocess.call([sys.executable, str(ROOT / "scripts" / "live.py"), *args], env=os.environ.copy())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
