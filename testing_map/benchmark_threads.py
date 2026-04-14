#!/usr/bin/env python3
"""
Benchmark solver thread counts for a generated Taguchi case and estimate
injection-stage thread utilization before running a full sweep.

Outputs:
  - thread_benchmark_report.csv
  - thread_benchmark_summary.txt

The script uses `case_params.json` when available so it stays aligned with
the current generated case settings.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def clean_cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_int(value: object, default: int = 0) -> int:
    text = clean_cell(value)
    if not text:
        return default
    return int(float(text))


def parse_float(value: object, default: float = 0.0) -> float:
    text = clean_cell(value)
    if not text:
        return default
    return float(text)


def ensure_within(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"Refusing to touch path outside benchmark root: {child_resolved}") from exc


def load_solver_flags(case_dir: Path) -> Dict[str, str]:
    case_json = case_dir / "case_params.json"
    if case_json.exists():
        payload = json.loads(case_json.read_text(encoding="utf-8"))
        raw_flags = payload.get("solver_flags", {})
        return {clean_cell(k): clean_cell(v) for k, v in raw_flags.items()}

    command_txt = case_dir / "command.txt"
    if not command_txt.exists():
        raise FileNotFoundError(f"Could not find case_params.json or command.txt in {case_dir}")

    tokens_list = shlex.split(command_txt.read_text(encoding="utf-8").strip(), posix=False)
    flags: Dict[str, str] = {}
    i = 1
    while i < len(tokens_list):
        token = tokens_list[i]
        if token.startswith("--") and i + 1 < len(tokens_list):
            flags[token[2:]] = tokens_list[i + 1]
            i += 2
        else:
            i += 1
    return flags


def build_command(exe_path: Path, flags: Dict[str, str]) -> List[str]:
    cmd = [str(exe_path)]
    for key, value in flags.items():
        if clean_cell(value) == "":
            continue
        cmd.extend([f"--{key}", clean_cell(value)])
    return cmd


def auto_thread_candidates(cpu_count: int) -> List[int]:
    # Mirror the timed-scaling sweep so quick benchmarks inspect the same plateau region.
    candidates = {1, 2, 4, 8, cpu_count}
    for value in (12, 16, 18, 24, 27, 32):
        if value <= cpu_count:
            candidates.add(value)
    if cpu_count >= 6:
        candidates.add(cpu_count // 2)
    if cpu_count >= 12:
        candidates.add(max(1, (3 * cpu_count) // 4))
    return sorted(x for x in candidates if 1 <= x <= cpu_count)


def parse_thread_list(text: str, cpu_count: int) -> List[int]:
    text = clean_cell(text)
    if not text:
        return auto_thread_candidates(cpu_count)
    values: List[int] = []
    for chunk in text.split(","):
        value = int(chunk.strip())
        if value <= 0:
            raise ValueError(f"Thread counts must be positive integers: {text}")
        values.append(value)
    return sorted(set(values))


def simulate_injection_schedule(flags: Dict[str, str]) -> Tuple[Counter, int, int]:
    dt = parse_float(flags.get("dt"), 0.0)
    flux = parse_float(flags.get("flux"), 0.0)
    fill_time = parse_float(flags.get("fill_time"), 0.0)
    natoms_max = parse_int(flags.get("natoms_max"), 0)
    niter = parse_int(flags.get("niter"), 0)

    hist: Counter = Counter()
    injected_total = 0
    steps_considered = 0

    if dt <= 0.0 or flux <= 0.0 or fill_time <= 0.0 or natoms_max <= 0 or niter < 0:
        return hist, 0, 0

    for it in range(niter + 1):
        t = it * dt
        if t >= fill_time or injected_total >= natoms_max:
            break
        should = int(math.floor(t * flux))
        want = min(should - injected_total, natoms_max - injected_total)
        if it == 0:
            want = max(want, 1)
        want = max(0, want)
        hist[want] += 1
        injected_total += want
        steps_considered += 1

    return hist, steps_considered, injected_total


def injection_summary_lines(flags: Dict[str, str], thread_counts: Sequence[int]) -> List[str]:
    dt = parse_float(flags.get("dt"), 0.0)
    flux = parse_float(flags.get("flux"), 0.0)
    hist, fill_steps, injected_total = simulate_injection_schedule(flags)
    active_steps = sum(count for want, count in hist.items() if want > 0)
    avg_atoms_per_step = flux * dt if dt > 0.0 else 0.0
    max_batch = max(hist) if hist else 0

    lines = [
        "Injection-stage parallelism estimate",
        f"  dt={dt:.6g} s, flux={flux:.6g} 1/s, flux*dt={avg_atoms_per_step:.6g} atoms/step",
        f"  evaluated fill steps={fill_steps}, scheduled injected atoms={injected_total}",
        f"  active injection steps={active_steps}, max batch size per step={max_batch}",
    ]

    if hist:
        nonzero_bins = [f"want={want}: {count}" for want, count in sorted(hist.items()) if count > 0]
        lines.append("  injection batch histogram: " + ", ".join(nonzero_bins))

    if avg_atoms_per_step < 1.0:
        if avg_atoms_per_step > 0.0:
            lines.append(
                f"  warning: flux*dt < 1, so most steps add no particles and active steps add about 1 particle every {1.0 / avg_atoms_per_step:.1f} steps"
            )
        else:
            lines.append("  warning: no scheduled injection work was detected from the current flags")

    if active_steps > 0:
        for thread_count in thread_counts:
            active_thread_sum = sum(min(thread_count, want) * count for want, count in hist.items() if want > 0)
            util_sum = sum((min(thread_count, want) / thread_count) * count for want, count in hist.items() if want > 0)
            avg_active = active_thread_sum / active_steps
            avg_util = 100.0 * util_sum / active_steps
            lines.append(
                f"  threads={thread_count}: insertion loop uses about {avg_active:.2f} active threads on active steps ({avg_util:.1f}% utilization)"
            )

    return lines


def remove_run_dir(run_dir: Path, out_root: Path) -> None:
    if run_dir.exists():
        ensure_within(out_root, run_dir)
        shutil.rmtree(run_dir)


def benchmark_one(
    exe_path: Path,
    base_flags: Dict[str, str],
    thread_count: int,
    run_dir: Path,
    inherit_stdout: bool,
) -> Tuple[float, int]:
    run_dir.mkdir(parents=True, exist_ok=True)

    flags = dict(base_flags)
    flags["threads"] = str(thread_count)
    flags["log_file"] = "solver_output.log"

    cmd = build_command(exe_path, flags)
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(thread_count)
    env["OMP_THREAD_LIMIT"] = str(thread_count)

    stdout_target = None
    stderr_target = None
    log_capture = None
    if not inherit_stdout:
        log_capture = (run_dir / "benchmark_stdout.log").open("w", encoding="utf-8")
        stdout_target = log_capture
        stderr_target = subprocess.STDOUT

    started = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=run_dir,
            env=env,
            check=False,
            stdout=stdout_target,
            stderr=stderr_target,
        )
    finally:
        if log_capture is not None:
            log_capture.close()
    elapsed = time.perf_counter() - started
    return elapsed, result.returncode


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    fieldnames = [
        "thread_count",
        "repeat_index",
        "elapsed_seconds",
        "return_code",
        "status",
        "run_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def aggregate_rows(rows: Sequence[Dict[str, object]]) -> List[Tuple[int, int, float, float, float]]:
    grouped: Dict[int, List[float]] = {}
    for row in rows:
        if row["status"] != "ok":
            continue
        grouped.setdefault(int(row["thread_count"]), []).append(float(row["elapsed_seconds"]))

    summary: List[Tuple[int, int, float, float, float]] = []
    for thread_count, values in sorted(grouped.items()):
        summary.append((thread_count, len(values), sum(values) / len(values), min(values), max(values)))
    return summary


def format_summary(
    case_dir: Path,
    exe_path: Path,
    base_flags: Dict[str, str],
    rows: Sequence[Dict[str, object]],
    thread_counts: Sequence[int],
) -> str:
    lines: List[str] = []
    lines.append(f"Case directory: {case_dir}")
    lines.append(f"Executable: {exe_path}")
    lines.append("")
    lines.extend(injection_summary_lines(base_flags, thread_counts))
    lines.append("")
    lines.append("Benchmark results")

    aggregates = aggregate_rows(rows)
    if not aggregates:
        lines.append("  no successful benchmark runs were recorded")
        return "\n".join(lines) + "\n"

    baseline = next((mean for thread_count, _, mean, _, _ in aggregates if thread_count == 1), None)
    best_thread, _, best_mean, _, _ = min(aggregates, key=lambda item: item[2])

    for thread_count, count, mean_val, min_val, max_val in aggregates:
        speedup_text = ""
        if baseline is not None and mean_val > 0.0:
            speedup_text = f", speedup vs 1 thread={baseline / mean_val:.3f}x"
        lines.append(
            f"  threads={thread_count}: repeats={count}, mean={mean_val:.3f}s, min={min_val:.3f}s, max={max_val:.3f}s{speedup_text}"
        )

    lines.append("")
    lines.append(f"Recommended thread count from this benchmark: {best_thread} (mean {best_mean:.3f}s)")

    failed = [row for row in rows if row["status"] != "ok"]
    if failed:
        lines.append("")
        lines.append("Failures")
        for row in failed:
            lines.append(
                f"  threads={row['thread_count']} repeat={row['repeat_index']} return_code={row['return_code']} run_dir={row['run_dir']}"
            )

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark thread counts for a generated case.")
    parser.add_argument("--case-dir", default="cases/run_001", help="Case folder to benchmark.")
    parser.add_argument("--exe", default=r"..\src\coax_pack_cpu.exe", help="Path to the solver executable.")
    parser.add_argument("--base-dir", default=".", help="Base directory for relative paths.")
    parser.add_argument("--threads", default="", help="Comma-separated thread counts. Default: auto-detect.")
    parser.add_argument("--repeats", type=int, default=2, help="Recorded repeats per thread count.")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup runs per thread count before measuring.")
    parser.add_argument("--out-dir", default="thread_benchmarks", help="Directory for benchmark outputs.")
    parser.add_argument("--niter-override", type=int, default=None, help="Override niter for quicker test runs.")
    parser.add_argument("--natoms-max-override", type=int, default=None, help="Override natoms_max for quicker test runs.")
    parser.add_argument("--fill-time-override", type=float, default=None, help="Override fill_time for quicker test runs.")
    parser.add_argument("--phi-target-override", type=float, default=None, help="Override phi_target for quicker test runs.")
    parser.add_argument("--analyze-only", action="store_true", help="Only estimate injection parallelism. Do not run solver benchmarks.")
    parser.add_argument("--show-solver-output", action="store_true", help="Let solver stdout stream to the console during benchmarks.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    case_dir = (base_dir / args.case_dir).resolve() if not Path(args.case_dir).is_absolute() else Path(args.case_dir)
    exe_path = (base_dir / args.exe).resolve() if not Path(args.exe).is_absolute() else Path(args.exe)
    out_root = (base_dir / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir)

    if not case_dir.exists():
        print(f"ERROR: case directory not found: {case_dir}", file=sys.stderr)
        return 1
    if not exe_path.exists():
        print(f"ERROR: solver executable not found: {exe_path}", file=sys.stderr)
        return 1

    cpu_count = max(1, os.cpu_count() or 1)
    thread_counts = parse_thread_list(args.threads, cpu_count)
    flags = load_solver_flags(case_dir)
    if args.niter_override is not None:
        flags["niter"] = str(args.niter_override)
    if args.natoms_max_override is not None:
        flags["natoms_max"] = str(args.natoms_max_override)
    if args.fill_time_override is not None:
        flags["fill_time"] = str(args.fill_time_override)
    if args.phi_target_override is not None:
        flags["phi_target"] = str(args.phi_target_override)

    out_root.mkdir(parents=True, exist_ok=True)
    case_out_root = out_root / case_dir.name
    case_out_root.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []

    print(f"Case: {case_dir}")
    print(f"Executable: {exe_path}")
    for line in injection_summary_lines(flags, thread_counts):
        print(line)

    if args.analyze_only:
        summary_path = case_out_root / "thread_benchmark_summary.txt"
        summary_text = format_summary(case_dir, exe_path, flags, rows, thread_counts)
        summary_path.write_text(summary_text, encoding="utf-8")
        print("")
        print(f"Wrote analysis summary: {summary_path}")
        return 0

    print("")
    print(f"Benchmarking thread counts: {', '.join(str(x) for x in thread_counts)}")

    for thread_count in thread_counts:
        for warmup_index in range(args.warmup):
            run_dir = case_out_root / f"threads_{thread_count:02d}" / f"warmup_{warmup_index + 1}"
            remove_run_dir(run_dir, out_root)
            print(f"Warmup: threads={thread_count} run={warmup_index + 1}/{args.warmup}")
            elapsed, return_code = benchmark_one(
                exe_path,
                flags,
                thread_count,
                run_dir,
                args.show_solver_output,
            )
            print(f"  warmup finished in {elapsed:.3f}s (return code {return_code})")
            if return_code != 0:
                print("  stopping after warmup failure", file=sys.stderr)
                rows.append(
                    {
                        "thread_count": thread_count,
                        "repeat_index": 0,
                        "elapsed_seconds": f"{elapsed:.6f}",
                        "return_code": return_code,
                        "status": "warmup_failed",
                        "run_dir": str(run_dir),
                    }
                )
                break
        else:
            for repeat_index in range(args.repeats):
                run_dir = case_out_root / f"threads_{thread_count:02d}" / f"repeat_{repeat_index + 1}"
                remove_run_dir(run_dir, out_root)
                print(f"Measure: threads={thread_count} repeat={repeat_index + 1}/{args.repeats}")
                elapsed, return_code = benchmark_one(
                    exe_path,
                    flags,
                    thread_count,
                    run_dir,
                    args.show_solver_output,
                )
                status = "ok" if return_code == 0 else "failed"
                print(f"  elapsed {elapsed:.3f}s (return code {return_code})")
                rows.append(
                    {
                        "thread_count": thread_count,
                        "repeat_index": repeat_index + 1,
                        "elapsed_seconds": f"{elapsed:.6f}",
                        "return_code": return_code,
                        "status": status,
                        "run_dir": str(run_dir),
                    }
                )

    report_path = case_out_root / "thread_benchmark_report.csv"
    summary_path = case_out_root / "thread_benchmark_summary.txt"
    write_csv(report_path, rows)
    summary_text = format_summary(case_dir, exe_path, flags, rows, thread_counts)
    summary_path.write_text(summary_text, encoding="utf-8")

    print("")
    print(f"Wrote report: {report_path}")
    print(f"Wrote summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
