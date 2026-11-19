"""Summarize paired replay rounds. Missing successes retain their scheduled denominator."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import median


def pooled(times, scheduled, p):
    n = math.ceil(scheduled * p)
    return times[n - 1] if n and n <= len(times) else None


def summarize(rows):
    groups = defaultdict(dict)
    for row in rows:
        key = (row["scenario"], row["fault"], row["strategy"])
        if row["seed"] in groups[key]:
            raise ValueError("duplicate round")
        groups[key][row["seed"]] = row
    result = []
    for (scenario, fault, strategy), by_seed in sorted(groups.items()):
        rounds = list(by_seed.values())
        host = "go.dev" if scenario == "A" else "moodle.must.edu.mo"
        times = sorted(
            at
            for row in rounds
            for source, at in row["marks"].items()
            if not row["sources"][source].startswith("https://" + host + "/")
        )
        scheduled = sum(row["healthy"] for row in rounds)

        result.append(
            {
                "scenario": scenario,
                "slow": fault,
                "strategy": strategy,
                "rounds": len(rounds),
                "healthy_success": len(times),
                "healthy_scheduled": scheduled,
                "pooled_p95": pooled(times, scheduled, 0.95),
                "pooled_p99": pooled(times, scheduled, 0.99),
                "round_median_p95": median(r["healthy_p95"] for r in rounds)
                if all(r["healthy_p95"] is not None for r in rounds)
                else None,
                "median_pages_per_s": median(r["pages_per_second"] for r in rounds),
                "median_cpu_s": median(r["cpu_seconds"] for r in rounds),
                "median_peak_mib": median(
                    r["rss_peak"] / (1024**2) for r in rounds if r["rss_peak"]
                ),
                "peak_site_concurrency": max(r["site_peak"] for r in rounds),
                "failed": sum(r["failed"] for r in rounds),
                "unfinished": sum(r["unfinished"] for r in rounds),
                "probes": sum(r["probe_requests"] for r in rounds),
            }
        )
    comparisons = []
    for scenario in ("A", "B"):
        for fault in (False, True):
            old = groups[scenario, fault, "baseline"]
            new = groups[scenario, fault, "round_robin"]
            paired = old.keys() & new.keys()
            diffs = [
                old[i]["healthy_p95"] - new[i]["healthy_p95"]
                for i in sorted(paired)
                if old[i]["healthy_p95"] is not None
                and new[i]["healthy_p95"] is not None
            ]
            if not diffs:
                continue
            rng = random.Random(20261119)
            ci = (
                sorted(median(rng.choices(diffs, k=len(diffs))) for _ in range(4000))
                if len(diffs) >= 20
                else None
            )
            comparisons.append(
                {
                    "scenario": scenario,
                    "slow": fault,
                    "usable_pairs": len(diffs),
                    "median_p95_reduction_s": median(diffs),
                    "paired_ci95": [ci[100], ci[3899]] if ci else None,
                }
            )
    return {"conditions": result, "paired": comparisons}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text().splitlines()]
    report = json.dumps(summarize(rows), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(report + "\n")
    else:
        print(report)
