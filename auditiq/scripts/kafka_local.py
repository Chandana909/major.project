"""A local Kafka broker for development and tests: one node in KRaft mode, without Docker or a service.

    python scripts/kafka_local.py init kafka_2.13-4.3.2.tgz   unpack the release, format the storage, write
                                                              AUDITIQ_KAFKA_BOOTSTRAP to .env
    python scripts/kafka_local.py start
    python scripts/kafka_local.py stop
    python scripts/kafka_local.py status
    python scripts/kafka_local.py reset                       stop, delete every topic and message, format again

Needs Java 17 or later (on PATH, or JAVA_HOME) and a Kafka release: download
kafka_2.13-<version>.tgz from https://kafka.apache.org/downloads and check it
against the SHA-512 published beside it. Locations:

    AUDITIQ_KAFKA_HOME   the unpacked release        (default: %LOCALAPPDATA%/auditiq/kafka)
    AUDITIQ_KAFKA_DATA   the broker's log directory   (default: %LOCALAPPDATA%/auditiq/kafka-data)
    AUDITIQ_KAFKA_PORT   port, on localhost only      (default: 9092; the controller uses the next one)

The broker listens on localhost only and keeps messages until `reset` (no time
limit: deleting log segments is unreliable on Windows).
"""
from __future__ import annotations

import os
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "auditiq"
HOME = Path(os.environ.get("AUDITIQ_KAFKA_HOME") or BASE / "kafka")
DATA = Path(os.environ.get("AUDITIQ_KAFKA_DATA") or BASE / "kafka-data")
PORT = int(os.environ.get("AUDITIQ_KAFKA_PORT", "9092"))
CONFIG = BASE / "kafka-local.properties"
PID_FILE = BASE / "kafka.pid"
LOG_FILE = BASE / "kafka.log"
ENV_FILE = PROJECT_ROOT / ".env"
WINDOWS = os.name == "nt"


def java(main_class: str, *args, server: bool = False) -> list[str]:
    """The command that runs one of Kafka's main classes. Java is called directly with the classpath `libs/*`: the
    release's .bat scripts list every jar's full path, which overflows cmd's line length in a long folder."""
    if not (HOME / "libs").exists():
        raise SystemExit(f"{HOME / 'libs'} not found; run `init` with the downloaded release, or set AUDITIQ_KAFKA_HOME")
    home = os.environ.get("JAVA_HOME")
    executable = str(Path(home) / "bin" / "java") if home else shutil.which("java")
    if not executable:
        raise SystemExit("Java 17 or later is needed (on PATH, or JAVA_HOME)")
    logging = HOME / "config" / ("log4j2.yaml" if server else "tools-log4j2.yaml")
    memory = ["-Xms512M", "-Xmx512M", "-XX:+UseG1GC"] if server else ["-Xmx256M"]
    return [executable, *memory, f"-Dlog4j2.configurationFile=file:{logging.as_posix()}",
            f"-Dkafka.logs.dir={(BASE / 'kafka-logs').as_posix()}", "-cp", f"{(HOME / 'libs').as_posix()}/*",
            main_class, *map(str, args)]


def properties() -> str:
    data = DATA.as_posix()          # forward slashes: a backslash is an escape in a properties file
    return f"""# Written by scripts/kafka_local.py: one node that is both broker and controller.
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@127.0.0.1:{PORT + 1}
listeners=PLAINTEXT://127.0.0.1:{PORT},CONTROLLER://127.0.0.1:{PORT + 1}
advertised.listeners=PLAINTEXT://127.0.0.1:{PORT}
controller.listener.names=CONTROLLER
inter.broker.listener.name=PLAINTEXT
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
log.dirs={data}
num.partitions=4
auto.create.topics.enable=false
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
share.coordinator.state.topic.replication.factor=1
share.coordinator.state.topic.min.isr=1
group.initial.rebalance.delay.ms=0
log.retention.hours=-1
# Compaction replaces a segment by renaming files, which fails on Windows while the segment is open: the broker
# then takes its log directory offline and stops. A development broker does without it.
log.cleaner.enable=false
"""


def write_env(key: str, value: str) -> None:
    """Set one key in .env, keeping every other line as it is."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    lines = [line for line in lines if not line.startswith(f"{key}=")] + [f"{key}={value}"]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def listening(port: int = PORT) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0




def format_storage() -> None:
    CONFIG.write_text(properties(), encoding="utf-8")
    DATA.mkdir(parents=True, exist_ok=True)
    cluster = str(uuid.uuid4().hex[:22])
    done = subprocess.run(java("kafka.tools.StorageTool", "format", "-t", cluster, "-c", CONFIG),
                          capture_output=True, text=True, cwd=HOME)
    if done.returncode:
        raise SystemExit(f"formatting the storage failed:\n{done.stdout}{done.stderr}")


def init(release: Path) -> None:
    if HOME.exists():
        raise SystemExit(f"{HOME} exists already; remove it to unpack another release")
    if not shutil.which("java") and not os.environ.get("JAVA_HOME"):
        raise SystemExit("Java 17 or later is needed (on PATH, or JAVA_HOME)")
    with tarfile.open(release) as archive:
        top = archive.getnames()[0].split("/")[0]
        if hasattr(tarfile, "data_filter"):
            archive.extractall(BASE, filter="data")
        else:                       # Python before 3.11.4: check by hand that nothing lands outside BASE
            root = BASE.resolve()
            for member in archive.getmembers():
                target = (BASE / member.name).resolve()
                if root not in target.parents or member.issym() or member.islnk() or member.isdev():
                    raise SystemExit(f"refusing to unpack {member.name!r}: not a plain file inside the release")
            archive.extractall(BASE)
    (BASE / top).rename(HOME)
    format_storage()
    for key in ("AUDITIQ_KAFKA_BOOTSTRAP", "AUDITIQ_TEST_KAFKA_BOOTSTRAP"):     # the tests use topics of their own
        write_env(key, f"127.0.0.1:{PORT}")
    print(f"Kafka unpacked to {HOME}, storage in {DATA}; AUDITIQ_KAFKA_BOOTSTRAP and AUDITIQ_TEST_KAFKA_BOOTSTRAP "
          f"(127.0.0.1:{PORT}) written to .env")


def writable(folder: Path) -> int:
    """Kafka marks a finished metadata snapshot read-only. On Windows a read-only file cannot be deleted, so when
    Kafka replaces the snapshot it cannot delete the old one, and it stops, at that moment and at every start after.
    Clear the flag on the broker's files before it starts; returns how many files had it."""
    cleared = 0
    for path in folder.rglob("*"):
        if path.is_file() and not os.access(path, os.W_OK):
            path.chmod(stat.S_IREAD | stat.S_IWRITE)
            cleared += 1
    return cleared


def start() -> None:
    if listening():
        print(f"a broker is already listening on localhost:{PORT}")
        return
    if not CONFIG.exists():
        raise SystemExit("not initialised: run `init` first")
    CONFIG.write_text(properties(), encoding="utf-8")       # the settings of this script, also for an older install
    if WINDOWS and DATA.exists() and (cleared := writable(DATA)):
        print(f"cleared the read-only flag of {cleared} file(s) Kafka could not otherwise delete")
    log = LOG_FILE.open("w", encoding="utf-8")
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if WINDOWS else 0
    process = subprocess.Popen(java("kafka.Kafka", CONFIG, server=True), cwd=HOME, stdout=log,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                               start_new_session=not WINDOWS)
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    deadline = time.monotonic() + 90
    while not listening():
        if process.poll() is not None or time.monotonic() > deadline:
            raise SystemExit(f"the broker did not start; see {LOG_FILE}")
        time.sleep(0.5)
    print(f"Kafka is listening on localhost:{PORT} (log: {LOG_FILE})")


def stop() -> None:
    if not PID_FILE.exists():
        print("not started by this script" if not listening() else "a broker not started by this script is running")
        return
    pid = int(PID_FILE.read_text(encoding="utf-8"))
    if WINDOWS:     # a detached Java process takes no console signal: end it
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 15)            # Kafka shuts down cleanly on SIGTERM
    deadline = time.monotonic() + 30
    while listening() and time.monotonic() < deadline:
        time.sleep(0.5)
    PID_FILE.unlink(missing_ok=True)
    print("stopped" if not listening() else "the broker is still listening")


def status() -> None:
    if not listening():
        print(f"no broker on localhost:{PORT}")
        return
    sys.path.insert(0, str(PROJECT_ROOT))
    from confluent_kafka.admin import AdminClient
    topics = AdminClient({"bootstrap.servers": f"127.0.0.1:{PORT}"}).list_topics(timeout=10).topics
    print(f"Kafka on localhost:{PORT}: {len(topics)} topic(s)")
    for name in sorted(t for t in topics if not t.startswith("__")):
        print(f"  {name:32s} {len(topics[name].partitions)} partition(s)")


def reset() -> None:
    stop()
    shutil.rmtree(DATA, ignore_errors=True)
    format_storage()
    print(f"every topic and message deleted; storage formatted again in {DATA}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "init":
        if len(sys.argv) < 3:
            raise SystemExit("usage: kafka_local.py init <kafka_2.13-version.tgz>")
        init(Path(sys.argv[2]))
    elif action in ("start", "stop", "status", "reset"):
        globals()[action]()
    else:
        raise SystemExit(__doc__)
