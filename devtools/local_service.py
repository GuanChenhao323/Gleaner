"""Start/inspect/stop only the local processes created by this launcher."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "local-services"
SCRIPTS = {"app": "devtools/dev_all.py", "fixture": "devtools/campus_fixture/app.py"}
PORTS = {"app": 8080, "fixture": 8098}


class LocalService:
    def __init__(self, name: str) -> None:
        self.name, self.script = name, ROOT / SCRIPTS[name]
        self.record = STATE / f"{name}.json"
        self.log = STATE / f"{name}.log"

    def running(self) -> dict | None:
        if not self.record.exists():
            return None
        saved = json.loads(self.record.read_text())
        probe = subprocess.run(
            ["ps", "-p", str(saved["pid"]), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode or str(self.script) not in probe.stdout:
            return None
        # A reused PID must not authorize stopping a different invocation.
        started = subprocess.run(
            ["ps", "-p", str(saved["pid"]), "-o", "lstart="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return saved if started == saved["started"] else None

    def status(self) -> None:
        saved = self.running()
        reachable = False
        try:
            with socket.create_connection(("127.0.0.1", PORTS[self.name]), timeout=1):
                reachable = True
        except OSError:
            pass
        print(
            json.dumps(
                {
                    "service": self.name,
                    "running": bool(saved),
                    "port_open": reachable,
                    "pid": saved["pid"] if saved else None,
                    "log": str(self.log),
                    "fixture_test_interval": saved.get("fixture_test_interval", 0)
                    if saved and self.name == "app"
                    else 0,
                },
                ensure_ascii=False,
            )
        )

    def start(self, *, fixture_test_interval: int = 0) -> None:
        if self.running():
            self.status()
            return
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", PORTS[self.name])) == 0:
                raise SystemExit(
                    f"Port {PORTS[self.name]} already in use; inspect the existing service before reuse."
                )
        STATE.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, "-u", str(self.script)]
        if self.name == "fixture":
            args += ["--port", str(PORTS[self.name])]
        elif fixture_test_interval:
            args += ["--fixture-reading-interval", str(fixture_test_interval)]
        with self.log.open("ab") as output:
            proc = subprocess.Popen(
                args,
                cwd=ROOT,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        started = subprocess.run(
            ["ps", "-p", str(proc.pid), "-o", "lstart="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.record.write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "started": started,
                    "command": args,
                    "fixture_test_interval": fixture_test_interval,
                    "created_at": time.time(),
                }
            )
        )
        self.status()

    def stop(self) -> None:
        saved = self.running()
        if not saved:
            print(f"{self.name}: no matching managed process; nothing stopped")
            return
        os.killpg(saved["pid"], signal.SIGINT)
        print(f"{self.name}: SIGINT sent to managed process group {saved['pid']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"])
    parser.add_argument(
        "service", choices=["app", "fixture", "all"], default="all", nargs="?"
    )
    parser.add_argument(
        "--fixture-reading-interval",
        type=int,
        choices=[60],
        default=0,
        help="QA only: accelerate loopback sources; never affects real websites",
    )
    args = parser.parse_args()
    for name in SCRIPTS if args.service == "all" else [args.service]:
        service = LocalService(name)
        if args.action == "start":
            service.start(fixture_test_interval=args.fixture_reading_interval)
        else:
            getattr(service, args.action)()


if __name__ == "__main__":
    main()
