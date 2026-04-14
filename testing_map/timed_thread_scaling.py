#!/usr/bin/env python3
"""
Run a fixed-wall-time thread scaling sweep for one generated case and plot
threads vs. achieved solver step.

Outputs:
  - timed_thread_scaling.csv
  - timed_thread_scaling_summary.txt
  - timed_thread_scaling.png
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


IT_RE = re.compile(r"\bit=(\d+)\b")


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
        raise ValueError(f"Refusing to touch path outside output root: {child_resolved}") from exc


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
        value = clean_cell(value)
        if value == "":
            continue
        cmd.extend([f"--{key}", value])
    return cmd


def auto_thread_candidates(cpu_count: int) -> List[int]:
    # Use a denser sweep around the region where scaling usually starts to flatten.
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


def latest_step_from_artifacts(run_dir: Path) -> int:
    best = -1
    log_path = run_dir / "solver_output.log"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = IT_RE.search(line)
            if match:
                best = max(best, int(match.group(1)))
    for path in run_dir.glob("atoms_*.xyz"):
        match = re.fullmatch(r"atoms_(\d+)\.xyz", path.name)
        if match:
            best = max(best, int(match.group(1)))
    return best


def timed_run(
    exe_path: Path,
    base_flags: Dict[str, str],
    thread_count: int,
    duration_sec: float,
    grace_sec: float,
    run_dir: Path,
) -> Dict[str, object]:
    run_dir.mkdir(parents=True, exist_ok=True)

    flags = dict(base_flags)
    flags["threads"] = str(thread_count)
    flags["log_file"] = "solver_output.log"

    cmd = build_command(exe_path, flags)
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(thread_count)
    env["OMP_THREAD_LIMIT"] = str(thread_count)

    stdout_log_path = run_dir / "benchmark_stdout.log"
    with stdout_log_path.open("w", encoding="utf-8") as stdout_log:
        started = time.perf_counter()
        proc = subprocess.Popen(
            cmd,
            cwd=run_dir,
            env=env,
            stdout=stdout_log,
            stderr=subprocess.STDOUT,
        )

        timed_out = False
        return_code = None
        try:
            proc.wait(timeout=duration_sec)
            return_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.terminate()
            try:
                proc.wait(timeout=grace_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=grace_sec)
            return_code = proc.returncode

        elapsed = time.perf_counter() - started

    achieved_step = latest_step_from_artifacts(run_dir)
    status = "timed_out" if timed_out else ("ok" if return_code == 0 else "failed")
    steps_per_sec = (achieved_step / elapsed) if achieved_step >= 0 and elapsed > 0.0 else 0.0
    return {
        "thread_count": thread_count,
        "elapsed_seconds": elapsed,
        "achieved_step": achieved_step,
        "steps_per_sec": steps_per_sec,
        "return_code": return_code,
        "status": status,
        "run_dir": str(run_dir),
    }


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    fieldnames = [
        "thread_count",
        "elapsed_seconds",
        "achieved_step",
        "steps_per_sec",
        "return_code",
        "status",
        "run_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def draw_plot(rows: Sequence[Dict[str, object]], out_path: Path, duration_sec: float) -> None:
    valid_rows = [row for row in rows if int(row["achieved_step"]) >= 0]
    if not valid_rows:
        raise ValueError("No valid timing rows were available to plot")

    width = 1200
    height = 800
    margin_left = 110
    margin_right = 80
    margin_top = 80
    margin_bottom = 120

    plot_left = margin_left
    plot_right = width - margin_right
    plot_top = margin_top
    plot_bottom = height - margin_bottom
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    threads = [int(row["thread_count"]) for row in valid_rows]
    actual_steps = [int(row["achieved_step"]) for row in valid_rows]
    baseline_row = min(valid_rows, key=lambda row: int(row["thread_count"]))
    baseline_threads = int(baseline_row["thread_count"])
    baseline_steps = max(0, int(baseline_row["achieved_step"]))
    ideal_steps = [
        int(round(baseline_steps * (thread_count / baseline_threads))) if baseline_threads > 0 else 0
        for thread_count in threads
    ]

    x_min = min(threads)
    x_max = max(threads)
    if x_min == x_max:
        x_min -= 1
        x_max += 1

    y_max = max(max(actual_steps), max(ideal_steps), 1)
    y_top = int(math.ceil(y_max * 1.1 / 1000.0) * 1000.0)
    y_top = max(y_top, 1000)

    def x_to_px(x: float) -> float:
        return plot_left + (x - x_min) * plot_width / (x_max - x_min)

    def y_to_px(y: float) -> float:
        return plot_bottom - y * plot_height / y_top

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    axis_color = (40, 40, 40)
    grid_color = (220, 220, 220)
    actual_color = (42, 87, 165)
    ideal_color = (220, 70, 70)
    point_fill = (255, 255, 255)

    draw.rectangle([plot_left, plot_top, plot_right, plot_bottom], outline=axis_color, width=2)

    y_ticks = 6
    for tick in range(y_ticks + 1):
        y_val = y_top * tick / y_ticks
        y_px = y_to_px(y_val)
        draw.line([(plot_left, y_px), (plot_right, y_px)], fill=grid_color, width=1)
        label = f"{int(round(y_val)):,}"
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text((plot_left - 10 - (bbox[2] - bbox[0]), y_px - (bbox[3] - bbox[1]) / 2), label, fill=axis_color, font=font)

    for x_val in threads:
        x_px = x_to_px(x_val)
        draw.line([(x_px, plot_top), (x_px, plot_bottom)], fill=grid_color, width=1)
        label = str(x_val)
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text((x_px - (bbox[2] - bbox[0]) / 2, plot_bottom + 12), label, fill=axis_color, font=font)

    actual_points = [(x_to_px(t), y_to_px(s)) for t, s in zip(threads, actual_steps)]
    ideal_points = [(x_to_px(t), y_to_px(s)) for t, s in zip(threads, ideal_steps)]

    for i in range(len(ideal_points) - 1):
        x1, y1 = ideal_points[i]
        x2, y2 = ideal_points[i + 1]
        segments = 18
        for j in range(segments):
            if j % 2 == 0:
                xa = x1 + (x2 - x1) * j / segments
                ya = y1 + (y2 - y1) * j / segments
                xb = x1 + (x2 - x1) * (j + 1) / segments
                yb = y1 + (y2 - y1) * (j + 1) / segments
                draw.line([(xa, ya), (xb, yb)], fill=ideal_color, width=3)

    draw.line(actual_points, fill=actual_color, width=4)
    for x_px, y_px in actual_points:
        r = 6
        draw.ellipse([x_px - r, y_px - r, x_px + r, y_px + r], outline=actual_color, fill=point_fill, width=3)

    title = f"Timed Thread Scaling ({duration_sec:.0f} s per thread)"
    subtitle = "Measured achieved step vs. ideal linear scaling from the smallest-thread baseline"
    draw.text((plot_left, 20), title, fill=axis_color, font=font)
    draw.text((plot_left, 42), subtitle, fill=(90, 90, 90), font=font)

    x_label = "Thread Count"
    y_label = "Last Reported Solver Step"
    x_bbox = draw.textbbox((0, 0), x_label, font=font)
    draw.text((plot_left + (plot_width - (x_bbox[2] - x_bbox[0])) / 2, height - 40), x_label, fill=axis_color, font=font)
    draw.text((20, plot_top - 18), y_label, fill=axis_color, font=font)

    legend_x = plot_right - 240
    legend_y = plot_top + 10
    draw.rectangle([legend_x, legend_y, legend_x + 220, legend_y + 60], outline=grid_color, fill=(252, 252, 252))
    draw.line([(legend_x + 12, legend_y + 18), (legend_x + 52, legend_y + 18)], fill=actual_color, width=4)
    draw.text((legend_x + 62, legend_y + 11), "Measured", fill=axis_color, font=font)
    for j in range(6):
        if j % 2 == 0:
            xa = legend_x + 12 + 40 * j / 6
            xb = legend_x + 12 + 40 * (j + 1) / 6
            draw.line([(xa, legend_y + 42), (xb, legend_y + 42)], fill=ideal_color, width=3)
    draw.text((legend_x + 62, legend_y + 35), "Ideal linear scaling", fill=axis_color, font=font)

    image.save(out_path)


def format_summary(
    case_dir: Path,
    exe_path: Path,
    rows: Sequence[Dict[str, object]],
    flags: Dict[str, str],
    thread_counts: Sequence[int],
    duration_sec: float,
    plot_path: Path,
) -> str:
    lines: List[str] = []
    lines.append(f"Case directory: {case_dir}")
    lines.append(f"Executable: {exe_path}")
    lines.append(f"Target runtime per thread count: {duration_sec:.1f} s")
    lines.append("")
    lines.extend(injection_summary_lines(flags, thread_counts))
    lines.append("")
    lines.append("Timed scaling results")
    for row in rows:
        lines.append(
            f"  threads={row['thread_count']}: achieved_step={row['achieved_step']}, elapsed={float(row['elapsed_seconds']):.3f}s, steps_per_sec={float(row['steps_per_sec']):.1f}, status={row['status']}, return_code={row['return_code']}"
        )
    valid_rows = [row for row in rows if int(row["achieved_step"]) >= 0]
    if valid_rows:
        best_row = max(valid_rows, key=lambda row: int(row["achieved_step"]))
        baseline_row = min(valid_rows, key=lambda row: int(row["thread_count"]))
        lines.append("")
        lines.append(
            f"Best measured throughput: {best_row['thread_count']} threads with achieved_step={best_row['achieved_step']} ({float(best_row['steps_per_sec']):.1f} steps/s)"
        )
        if int(baseline_row["thread_count"]) > 0 and int(baseline_row["achieved_step"]) > 0:
            measured_scale = int(best_row["achieved_step"]) / int(baseline_row["achieved_step"])
            ideal_scale = int(best_row["thread_count"]) / int(baseline_row["thread_count"])
            lines.append(
                f"Scaling vs baseline ({baseline_row['thread_count']} thread): measured={measured_scale:.3f}x, ideal={ideal_scale:.3f}x"
            )
    lines.append(f"Plot: {plot_path}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a fixed-duration thread scaling sweep and save a PNG plot.")
    parser.add_argument("--case-dir", default="cases/run_001", help="Case folder to benchmark.")
    parser.add_argument("--exe", default=r"..\src\coax_pack_cpu.exe", help="Path to the solver executable.")
    parser.add_argument("--base-dir", default=".", help="Base directory for relative paths.")
    parser.add_argument("--threads", default="", help="Comma-separated thread counts. Default: auto-detect.")
    parser.add_argument("--duration-sec", type=float, default=60.0, help="Wall-clock duration per thread count.")
    parser.add_argument("--grace-sec", type=float, default=5.0, help="Extra time to wait after terminate before kill.")
    parser.add_argument("--out-dir", default="thread_benchmarks", help="Directory for scaling outputs.")
    parser.add_argument("--min-niter", type=int, default=1000000, help="Raise niter to at least this value so the run does not finish too early.")
    parser.add_argument("--progress-interval", type=int, default=1000, help="dump_interval used during the timed sweep.")
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
    flags["niter"] = str(max(parse_int(flags.get("niter"), 0), args.min_niter))
    flags["dump_interval"] = str(max(1, args.progress_interval))
    flags["xyz_interval"] = "0"
    flags["vtk_interval"] = "0"
    flags["vtk_domain_interval"] = "0"
    flags["dump_final_xyz"] = "0"
    flags["debug"] = "1"

    case_out_root = out_root / case_dir.name / "timed_scaling"
    case_out_root.mkdir(parents=True, exist_ok=True)

    print(f"Case: {case_dir}")
    print(f"Executable: {exe_path}")
    for line in injection_summary_lines(flags, thread_counts):
        print(line)
    print("")
    print(f"Running timed sweep for {args.duration_sec:.1f} seconds per thread count")

    rows: List[Dict[str, object]] = []
    for thread_count in thread_counts:
        run_dir = case_out_root / f"threads_{thread_count:02d}"
        remove_run_dir(run_dir, out_root)
        print(f"Timed run: threads={thread_count}")
        row = timed_run(exe_path, flags, thread_count, args.duration_sec, args.grace_sec, run_dir)
        rows.append(row)
        print(
            f"  achieved_step={row['achieved_step']} elapsed={float(row['elapsed_seconds']):.3f}s status={row['status']} return_code={row['return_code']}"
        )

    csv_path = case_out_root / "timed_thread_scaling.csv"
    summary_path = case_out_root / "timed_thread_scaling_summary.txt"
    plot_path = case_out_root / "timed_thread_scaling.png"

    write_csv(csv_path, rows)
    draw_plot(rows, plot_path, args.duration_sec)
    summary_text = format_summary(case_dir, exe_path, rows, flags, thread_counts, args.duration_sec, plot_path)
    summary_path.write_text(summary_text, encoding="utf-8")

    print("")
    print(f"Wrote CSV: {csv_path}")
    print(f"Wrote summary: {summary_path}")
    print(f"Wrote plot: {plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
