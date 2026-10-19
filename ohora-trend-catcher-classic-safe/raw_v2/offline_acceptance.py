#!/usr/bin/env python3
"""Offline, read-only operational acceptance: no Meta calls, DB edits, or scheduler install."""
import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--report-dir", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parent.parent
    out = a.output_dir.resolve()
    dest = a.report_dir.resolve()
    if dest == out or dest.is_relative_to(out):
        p.error("report-dir must be outside output-dir")
    dest.mkdir(parents=True, exist_ok=True)
    commands = [
        ("offline_tests", [sys.executable, str(root / "tests" / "run_offline.py")]),
        ("audit", [sys.executable, str(root / "raw_v2" / "audit.py"), "--output-dir", str(out), "--report-dir", str(dest / "audit")]),
        ("recovery_preview", [sys.executable, str(root / "raw_v2" / "recover.py"), "--output-dir", str(out)]),
        ("scheduler_dry_run", [sys.executable, str(root / "raw_v2" / "daily_scheduler.py"), "--source", str(a.source), "--output-dir", str(out), "--policy", "daily"]),
    ]
    results = {}
    for name, cmd in commands:
        print("RUN", name, flush=True)
        try:
            r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=180, check=False)
            results[name] = {"exit_code": r.returncode, "stdout": r.stdout[-12000:], "stderr": r.stderr[-4000:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            results[name] = {"exit_code": None, "error": str(exc)}
        print(name, "EXIT", results[name]["exit_code"], flush=True)
    summary_path = dest / "audit" / "summary.json"
    findings_path = dest / "audit" / "coverage_findings.csv"
    audit_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    findings = []
    if findings_path.exists():
        with findings_path.open(encoding="utf-8-sig", newline="") as f:
            findings = list(csv.DictReader(f))
    counts = Counter(x.get("code", "") for x in findings)
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "offline only; no Meta quota, live API, long-run reliability, or full historical coverage claim",
        "checks": results,
        "audit_summary": audit_summary,
        "coverage_by_code": dict(counts),
        "coverage_findings": findings,
        "offline_checks_pass": all(results[k]["exit_code"] == 0 for k in ("offline_tests", "audit", "recovery_preview", "scheduler_dry_run")),
        "unattended_collection_approved": False,
    }
    (dest / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("COVERAGE_BY_CODE", json.dumps(dict(counts), ensure_ascii=False))
    for row in findings:
        print("COVERAGE", row.get("account_key"), row.get("code"), row.get("detail"))
    print("OFFLINE_CHECKS_PASS", report["offline_checks_pass"])
    print("UNATTENDED_COLLECTION_APPROVED", False)
    print("REPORT", dest / "acceptance.json")
    return 0 if report["offline_checks_pass"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
