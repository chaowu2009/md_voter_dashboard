from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STEPS = [
    ("step1", ROOT / "step1_parser.py"),
    ("step2", ROOT / "step2_validate.py"),
    ("step3", ROOT / "step3_anomaly.py"),
    ("step4", ROOT / "step4_self_improve.py"),
]

RUNS_DIR = ROOT / "agent_runs"


@dataclass
class StepResult:
    step: str
    script: str
    status: str
    started_at: str
    ended_at: str
    duration_seconds: float
    return_code: int
    stdout_tail: list[str]
    stderr_tail: list[str]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tail_lines(text: str, max_lines: int = 30) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-max_lines:]


def run_step(step_name: str, script_path: Path) -> StepResult:
    started = datetime.now(timezone.utc)
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    ended = datetime.now(timezone.utc)

    status = "success" if proc.returncode == 0 else "failed"
    return StepResult(
        step=step_name,
        script=str(script_path.relative_to(ROOT)),
        status=status,
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        duration_seconds=round((ended - started).total_seconds(), 3),
        return_code=proc.returncode,
        stdout_tail=tail_lines(proc.stdout),
        stderr_tail=tail_lines(proc.stderr),
    )


def load_json_if_exists(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def collect_artifact_summary() -> dict:
    parsed_files = sorted((ROOT / "data/parsed").glob("MSR-*.csv"))
    validation_agg = load_json_if_exists(ROOT / "data/validation_reports/validation_aggregate.json")
    anomaly_summary = load_json_if_exists(ROOT / "data/anomaly_reports/anomaly_summary.json")
    step4_summary = load_json_if_exists(ROOT / "agent_suggestions/step4_run_summary.json")

    return {
        "parsed_csv_count": len(parsed_files),
        "validation": validation_agg,
        "anomaly": anomaly_summary,
        "step4": step4_summary,
    }


def main() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    results: list[StepResult] = []
    for step_name, script in STEPS:
        if not script.exists():
            results.append(
                StepResult(
                    step=step_name,
                    script=str(script.relative_to(ROOT)),
                    status="failed",
                    started_at=now_iso(),
                    ended_at=now_iso(),
                    duration_seconds=0.0,
                    return_code=127,
                    stdout_tail=[],
                    stderr_tail=[f"Missing script: {script.name}"],
                )
            )
            break

        result = run_step(step_name, script)
        results.append(result)

        log_obj = {
            "step": result.step,
            "script": result.script,
            "status": result.status,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "duration_seconds": result.duration_seconds,
            "return_code": result.return_code,
            "stdout_tail": result.stdout_tail,
            "stderr_tail": result.stderr_tail,
        }
        (run_dir / f"{step_name}.json").write_text(json.dumps(log_obj, indent=2), encoding="utf-8")

        if result.status != "success":
            break

    overall_status = "success" if results and all(r.status == "success" for r in results) else "failed"

    summary = {
        "run_id": run_id,
        "started_at": results[0].started_at if results else now_iso(),
        "ended_at": results[-1].ended_at if results else now_iso(),
        "overall_status": overall_status,
        "steps": [
            {
                "step": r.step,
                "script": r.script,
                "status": r.status,
                "duration_seconds": r.duration_seconds,
                "return_code": r.return_code,
            }
            for r in results
        ],
        "artifacts": collect_artifact_summary(),
    }

    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (RUNS_DIR / "latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
