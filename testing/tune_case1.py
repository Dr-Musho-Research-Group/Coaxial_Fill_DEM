#!/usr/bin/env python3
"""
Tune a small set of CLI/process parameters for Taguchi case 1 using the
`testing` workflow.

Goal:
  - reach the requested packing fraction with the least wall time
  - keep the final fill reasonably uniform in both z and r
  - keep intermediate VTK output enabled so the fill path is inspectable

This script uses only the Python standard library so it can run in the same
environment as the other local testing helpers.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


CASE1 = {
    "diameter_scale_factor": "0.9",
    "phi_target": "0.35",
    "f_la": "0.10",
    "f_sr": "0.10",
    "f_fe": "0.70",
    "f_co": "0.10",
}


BASE_FLAGS: Dict[str, str] = {
    "natoms_max": "25000",
    # The current best probe used a larger dt and shorter niter cap, then
    # relied on solver-side early-stop once phi_target and settle criteria
    # were both satisfied.
    "dt": "4e-6",
    "niter": "120000",
    "dump_interval": "10000",
    "debug": "1",
    "seed": "42",
    "threads": "4",
    "omp_min_particles": "512",
    "rin": "23e-6",
    "rout": "39e-6",
    "length": "379e-6",
    "gravity": "0.0",
    "shake_hz": "1000",
    "shake_amp": "0",
    "shake_amp_x": "0",
    "shake_amp_y": "0",
    "shake_amp_z": "0",
    "shake_xy_legacy": "0",
    "cushion": "1E-7",
    "wall_k": "0.0",
    "wall_zeta": "0.20",
    "wall_dvmax": "5.0",
    "wall_rough_amp": "0",
    "wall_rough_mth": "8",
    "wall_rough_mz": "3",
    "e_pp": "0.20",
    "e_pw": "0.15",
    "tangent_damp": "0.90",
    "repulse_range": "0.5e-5",
    "repulse_k_pp": "2000",
    "repulse_k_pw": "500",
    "repulse_use_mass": "0",
    "repulse_dvmax": "0.2",
    "xyz_interval": "0",
    "vtk_interval": "10000",
    "vtk_domain_interval": "0",
    "vtk_domain_segments": "96",
    "dump_final_xyz": "1",
    "dump_final_vtk": "1",
    "adaptive_composition": "1",
    **CASE1,
}


@dataclass
class Candidate:
    name: str
    description: str
    overrides: Dict[str, str]


CANDIDATES: List[Candidate] = [
    Candidate(
        name="probe_fast_balanced",
        description="Best finished probe so far: faster fill with stronger post-fill damping and relaxed settle checks.",
        overrides={
            "flux": "24000",
            "lin_damp": "800.0",
            "post_fill_lin_damp": "1500.0",
            "inject_vx": "0.0",
            "inject_vy": "0.0",
            "inject_vz": "-0.04",
            "fill_time": "8.0",
            "ram_start": "0.0",
            "ram_duration": "0.0",
            "ram_speed": "0.0",
            "stop_vrms": "0.0060",
            "stop_vmax": "0.120",
            "stop_sleep_frac": "0.0",
            "stop_check_interval": "1000",
            "stop_checks_required": "2",
        },
    ),
    Candidate(
        name="probe_tighter_stop",
        description="Same faster fill path but with slightly tighter settle thresholds for a cleaner final bed.",
        overrides={
            "flux": "24000",
            "lin_damp": "800.0",
            "post_fill_lin_damp": "1500.0",
            "inject_vx": "0.0",
            "inject_vy": "0.0",
            "inject_vz": "-0.04",
            "fill_time": "8.0",
            "ram_start": "0.0",
            "ram_duration": "0.0",
            "ram_speed": "0.0",
            "stop_vrms": "0.0050",
            "stop_vmax": "0.100",
            "stop_sleep_frac": "0.0",
            "stop_check_interval": "1000",
            "stop_checks_required": "3",
        },
    ),
    Candidate(
        name="probe_gentler_injection",
        description="Keep the faster timestep and damping, but soften the inlet velocity to favor a smoother bed.",
        overrides={
            "flux": "22000",
            "lin_damp": "850.0",
            "post_fill_lin_damp": "1500.0",
            "inject_vx": "0.0",
            "inject_vy": "0.0",
            "inject_vz": "-0.03",
            "fill_time": "8.0",
            "ram_start": "0.0",
            "ram_duration": "0.0",
            "ram_speed": "0.0",
            "stop_vrms": "0.0050",
            "stop_vmax": "0.100",
            "stop_sleep_frac": "0.0",
            "stop_check_interval": "1000",
            "stop_checks_required": "2",
        },
    ),
    Candidate(
        name="probe_more_damped_fill",
        description="Adds a bit more damping during fill while keeping the quicker post-fill settle path.",
        overrides={
            "flux": "24000",
            "lin_damp": "900.0",
            "post_fill_lin_damp": "1400.0",
            "inject_vx": "0.0",
            "inject_vy": "0.0",
            "inject_vz": "-0.04",
            "fill_time": "8.0",
            "ram_start": "0.0",
            "ram_duration": "0.0",
            "ram_speed": "0.0",
            "stop_vrms": "0.0055",
            "stop_vmax": "0.110",
            "stop_sleep_frac": "0.0",
            "stop_check_interval": "1000",
            "stop_checks_required": "2",
        },
    ),
]


IT_RE = re.compile(r"\bit=(\d+)\b")


def build_command(exe_path: Path, flags: Dict[str, str]) -> List[str]:
    cmd = [str(exe_path)]
    for key, value in flags.items():
        if str(value).strip() == "":
            continue
        cmd.extend([f"--{key}", str(value)])
    return cmd


def parse_xyz(path: Path) -> List[Tuple[str, float, float, float, float]]:
    rows: List[Tuple[str, float, float, float, float]] = []
    with path.open("r", encoding="utf-8") as handle:
        first = handle.readline().strip()
        if not first:
            return rows
        try:
            nrows = int(first)
        except ValueError:
            return rows
        _comment = handle.readline()
        for _ in range(nrows):
            parts = handle.readline().split()
            if len(parts) < 5:
                continue
            elem = parts[0]
            x = float(parts[1])
            y = float(parts[2])
            z = float(parts[3])
            diameter = float(parts[4])
            rows.append((elem, x, y, z, 0.5 * diameter))
    return rows


def sphere_volume(radius: float) -> float:
    return (4.0 / 3.0) * math.pi * radius ** 3


def coeff_var(values: Iterable[float]) -> float:
    data = [value for value in values if value > 0.0]
    if len(data) < 2:
        return 0.0
    mean_val = sum(data) / len(data)
    if mean_val <= 0.0:
        return 0.0
    var = sum((value - mean_val) ** 2 for value in data) / (len(data) - 1)
    return math.sqrt(max(0.0, var)) / mean_val


def evaluate_fill(
    xyz_path: Path,
    rin: float,
    rout: float,
    length: float,
    phi_target: float,
    axial_bins: int = 16,
    radial_bins: int = 10,
) -> Dict[str, float]:
    rows = parse_xyz(xyz_path)
    if not rows:
        return {
            "particle_count": 0.0,
            "phi": 0.0,
            "axial_pf_cv": 999.0,
            "radial_pf_cv": 999.0,
            "bed_height": 0.0,
        }

    annulus_area = math.pi * (rout * rout - rin * rin)
    dom_vol = annulus_area * length

    total_vol = 0.0
    z_min = float("inf")
    z_max = float("-inf")
    r_min = rin
    r_max = rout

    for _elem, x, y, z, radius in rows:
        total_vol += sphere_volume(radius)
        z_min = min(z_min, z - radius)
        z_max = max(z_max, z + radius)

    bed_height = max(1e-12, z_max - z_min)
    phi = total_vol / dom_vol if dom_vol > 0.0 else 0.0

    axial_vol = [0.0 for _ in range(axial_bins)]
    axial_dz = bed_height / axial_bins
    radial_vol = [0.0 for _ in range(radial_bins)]
    radial_edges = [r_min + (r_max - r_min) * i / radial_bins for i in range(radial_bins + 1)]

    for _elem, x, y, z, radius in rows:
        vol = sphere_volume(radius)
        ax = int((z - z_min) / axial_dz) if axial_dz > 0.0 else 0
        ax = max(0, min(axial_bins - 1, ax))
        axial_vol[ax] += vol

        r = math.hypot(x, y)
        rb = radial_bins - 1
        for i in range(radial_bins):
            if r <= radial_edges[i + 1]:
                rb = i
                break
        radial_vol[rb] += vol

    axial_pf = [
        axial_vol[i] / (annulus_area * axial_dz) if annulus_area > 0.0 and axial_dz > 0.0 else 0.0
        for i in range(axial_bins)
    ]

    radial_pf: List[float] = []
    for i in range(radial_bins):
        shell_vol = math.pi * (radial_edges[i + 1] ** 2 - radial_edges[i] ** 2) * bed_height
        radial_pf.append(radial_vol[i] / shell_vol if shell_vol > 0.0 else 0.0)

    phi_penalty = abs(phi - phi_target)
    return {
        "particle_count": float(len(rows)),
        "phi": phi,
        "axial_pf_cv": coeff_var(axial_pf),
        "radial_pf_cv": coeff_var(radial_pf),
        "bed_height": bed_height,
        "phi_penalty": phi_penalty,
    }


def find_latest_xyz(run_dir: Path) -> Optional[Path]:
    best: Optional[Tuple[int, Path]] = None
    for path in run_dir.glob("atoms_*.xyz"):
        match = re.fullmatch(r"atoms_(\d+)\.xyz", path.name)
        if not match:
            continue
        step = int(match.group(1))
        if best is None or step > best[0]:
            best = (step, path)
    return None if best is None else best[1]


def parse_last_step(log_path: Path, xyz_path: Optional[Path]) -> int:
    best = -1
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = IT_RE.search(line)
            if match:
                best = max(best, int(match.group(1)))
    if xyz_path is not None:
        match = re.fullmatch(r"atoms_(\d+)\.xyz", xyz_path.name)
        if match:
            best = max(best, int(match.group(1)))
    return best


def candidate_score(elapsed_sec: float, stats: Dict[str, float], phi_target: float) -> float:
    # Weight wall time first, then penalize ragged final beds and missing the PF target.
    return elapsed_sec * (
        1.0
        + 0.80 * stats["axial_pf_cv"]
        + 0.45 * stats["radial_pf_cv"]
        + 8.0 * abs(stats["phi"] - phi_target)
    )


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    fieldnames = [
        "candidate",
        "description",
        "elapsed_seconds",
        "return_code",
        "last_step",
        "particle_count",
        "phi",
        "axial_pf_cv",
        "radial_pf_cv",
        "bed_height_m",
        "score",
        "run_dir",
        "final_xyz",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune CLI/process parameters for Taguchi case 1 using the testing workflow.")
    parser.add_argument("--base-dir", default=".", help="Base directory for relative paths.")
    parser.add_argument("--exe", default=r"..\src\coax_pack_cpu.exe", help="Path to the solver executable.")
    parser.add_argument("--out-dir", default="tuning_case1", help="Directory where candidate runs and reports are written.")
    parser.add_argument("--threads", default="4", help="Thread count for all runs.")
    parser.add_argument("--limit", type=int, default=0, help="Only run the first N candidates (0 means all).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    exe_path = (base_dir / args.exe).resolve() if not Path(args.exe).is_absolute() else Path(args.exe)
    out_root = (base_dir / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir)

    if not exe_path.exists():
        print(f"ERROR: solver executable not found: {exe_path}", file=sys.stderr)
        return 1

    candidates = CANDIDATES[: args.limit] if args.limit and args.limit > 0 else CANDIDATES
    out_root.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    rin = float(BASE_FLAGS["rin"])
    rout = float(BASE_FLAGS["rout"])
    length = float(BASE_FLAGS["length"])
    phi_target = float(CASE1["phi_target"])

    for candidate in candidates:
        run_dir = out_root / candidate.name
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        flags = dict(BASE_FLAGS)
        flags["threads"] = str(args.threads)
        flags.update(candidate.overrides)
        flags["log_file"] = "solver_output.log"

        cmd = build_command(exe_path, flags)
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(args.threads)
        env["OMP_THREAD_LIMIT"] = str(args.threads)

        print(f"Running {candidate.name} ...")
        started = time.perf_counter()
        result = subprocess.run(cmd, cwd=run_dir, env=env, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        elapsed = time.perf_counter() - started

        final_xyz = find_latest_xyz(run_dir)
        stats = evaluate_fill(final_xyz, rin, rout, length, phi_target) if final_xyz is not None else {
            "particle_count": 0.0,
            "phi": 0.0,
            "axial_pf_cv": 999.0,
            "radial_pf_cv": 999.0,
            "bed_height": 0.0,
            "phi_penalty": 999.0,
        }
        last_step = parse_last_step(run_dir / "solver_output.log", final_xyz)
        score = candidate_score(elapsed, stats, phi_target) if result.returncode == 0 else 1.0e12

        rows.append(
            {
                "candidate": candidate.name,
                "description": candidate.description,
                "elapsed_seconds": f"{elapsed:.3f}",
                "return_code": result.returncode,
                "last_step": last_step,
                "particle_count": int(stats["particle_count"]),
                "phi": f"{stats['phi']:.6f}",
                "axial_pf_cv": f"{stats['axial_pf_cv']:.6f}",
                "radial_pf_cv": f"{stats['radial_pf_cv']:.6f}",
                "bed_height_m": f"{stats['bed_height']:.6e}",
                "score": f"{score:.6f}",
                "run_dir": str(run_dir),
                "final_xyz": "" if final_xyz is None else str(final_xyz),
            }
        )
        print(
            f"  elapsed={elapsed:.1f}s rc={result.returncode} phi={stats['phi']:.4f} axial_cv={stats['axial_pf_cv']:.3f} radial_cv={stats['radial_pf_cv']:.3f} score={score:.2f}"
        )

    report_path = out_root / "tuning_report.csv"
    write_csv(report_path, rows)

    best_rows = [row for row in rows if int(row["return_code"]) == 0]
    summary_path = out_root / "tuning_summary.txt"
    with summary_path.open("w", encoding="utf-8") as handle:
        handle.write(f"Executable: {exe_path}\n")
        handle.write(f"Threads: {args.threads}\n")
        handle.write(f"Candidates tested: {len(rows)}\n\n")
        if best_rows:
            best = min(best_rows, key=lambda row: float(row["score"]))
            handle.write(f"Best candidate: {best['candidate']}\n")
            handle.write(f"Description: {best['description']}\n")
            handle.write(f"Elapsed seconds: {best['elapsed_seconds']}\n")
            handle.write(f"Final phi: {best['phi']}\n")
            handle.write(f"Axial packing CV: {best['axial_pf_cv']}\n")
            handle.write(f"Radial packing CV: {best['radial_pf_cv']}\n")
            handle.write(f"Run dir: {best['run_dir']}\n")
            handle.write(f"Final XYZ: {best['final_xyz']}\n")
        else:
            handle.write("No successful candidates were recorded.\n")

    print(f"Wrote report: {report_path}")
    print(f"Wrote summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
