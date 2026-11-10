"""Allowlisted metadata reports. Raw pages, credential values and URLs are never accepted."""

import json
from pathlib import Path


class Report:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, data: dict) -> None:
        allowed = {
            "request": {
                "kind",
                "path",
                "status",
                "wire_bytes",
                "decoded_bytes",
                "started_mono",
                "finished_mono",
                "utc",
                "redirect_path",
                "redirect_same_origin",
            },
            "observation": {
                "check_id",
                "observation_id",
                "scheduled_at",
                "started_at",
                "stub_receipt",
                "utc",
                "mono",
                "authentication",
                "evidence_code",
                "representation_hash",
                "entries",
                "error",
            },
            "run": {
                "run_id",
                "mode",
                "execution_mode",
                "sink_kind",
                "python",
                "httpx",
                "chrome",
                "adapter",
                "commit",
                "duration_s",
                "dns_mode",
                "started_at",
            },
            "summary": {
                "run_id",
                "finished_at",
                "elapsed_s",
                "successful_rounds",
                "failed_rounds",
                "passed",
                "reason",
                "missed_rounds",
                "interruptions",
                "elapsed_utc_s",
            },
            "interruption": {"utc", "mono", "reason"},
        }
        if kind not in allowed or set(data) - allowed[kind]:
            raise ValueError("report_field_denied")
        if kind == "observation":
            for entry in data.get("entries", []):
                if set(entry) - {
                    "item_id",
                    "outcome",
                    "title_present",
                    "text_length",
                    "error",
                }:
                    raise ValueError("report_field_denied")
                if entry.get("error") and set(entry["error"]) - {"code"}:
                    raise ValueError("report_field_denied")
            receipt = data.get("stub_receipt")
            if receipt and set(receipt) - {"applied", "state", "outcome", "results"}:
                raise ValueError("report_field_denied")
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps({"record": kind, **data}, ensure_ascii=False) + "\n")


class RunAudit:
    """Continuous-run acceptance, including missing rounds and wall-clock sleep gaps."""

    def __init__(self, interval_s: float, duration_s: float) -> None:
        self.interval_s, self.duration_s = interval_s, duration_s
        self.times: list[tuple[float, float]] = []
        self.failed_rounds = 0
        self.missed_rounds = 0
        self.interruptions: list[str] = []
        self._reported_gaps: set[tuple[float, float]] = set()
        self.max_gap_s = (
            interval_s + 35
        )  # 30 s request budget + 5 s polling/jitter tolerance.

    def interrupt(self, reason: str) -> None:
        if reason not in self.interruptions:
            self.interruptions.append(reason)

    def watchdog(self, mono: float, utc: float) -> None:
        if (
            self.times
            and max(mono - self.times[-1][0], utc - self.times[-1][1]) > self.max_gap_s
        ):
            if self.times[-1] not in self._reported_gaps:
                gap = max(mono - self.times[-1][0], utc - self.times[-1][1])
                self.missed_rounds += max(1, int(gap // self.interval_s) - 1)
                self._reported_gaps.add(self.times[-1])
            self.interrupt("missing_round")

    def observe(self, observation: dict) -> bool:
        self.watchdog(observation["mono"], observation["utc"])
        entries, receipt = (
            observation.get("entries", []),
            observation.get("stub_receipt", {}),
        )
        success = bool(
            observation.get("authentication") == "authenticated"
            and entries
            and all(e["outcome"] == "content" for e in entries)
            and receipt.get("applied")
            and receipt.get("state") == "succeeded"
        )
        if success:
            self.times.append((observation["mono"], observation["utc"]))
        else:
            self.failed_rounds += 1
        return success

    def result(self, mono: float, utc: float) -> dict:
        self.watchdog(mono, utc)
        elapsed = mono - self.times[0][0] if self.times else 0
        elapsed_utc = utc - self.times[0][1] if self.times else 0
        passed = bool(
            self.times
            and elapsed >= self.duration_s
            and elapsed_utc >= self.duration_s
            and self.times[-1][0] - self.times[0][0] > 7200
            and not self.failed_rounds
            and not self.missed_rounds
            and not self.interruptions
        )
        return {
            "elapsed_s": elapsed,
            "elapsed_utc_s": elapsed_utc,
            "successful_rounds": len(self.times),
            "failed_rounds": self.failed_rounds,
            "missed_rounds": self.missed_rounds,
            "interruptions": self.interruptions.copy(),
            "passed": passed,
            "reason": "completed" if passed else "stopped_or_failed",
        }
