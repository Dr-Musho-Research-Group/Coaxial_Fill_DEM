#!/usr/bin/env python3
"""
Create one case folder per row in a Taguchi test matrix and optionally run coax_pack_cpu.exe.

Expected CSV columns:
    Run, diameter_scale_factor, PF_value, f_La, f_Sr, f_Fe, f_Co

Behavior:
  - Creates a unique folder for each case under --case-root
  - Writes case_params.json and command.txt into each case folder
  - Writes a run_case.bat into each case folder for replay on Windows
  - Optionally executes each case with cwd set to the case folder so solver outputs stay isolated
  - Optionally runs _fill_stats.py and _atoms_plot_all.py after each simulation when available

This script mirrors the defaults from _run_win_cpu.bat, then overrides the case-specific values
from the CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


BASE_FLAGS: Dict[str, str] = {
    "natoms_max": "25000",
    "dt": "2e-6",
    "niter": "200000",
    "dump_interval": "1000",
    "debug": "1",
    "seed": "42",
    "threads": "0",
    "rin": "23e-6",
    "rout": "39e-6",
    "length": "379e-6",
    "flux": "20000",
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
    "lin_damp": "800.0",
    "e_pp": "0.20",
    "e_pw": "0.15",
    "tangent_damp": "0.90",
    "repulse_range": "0.5e-5",
    "repulse_k_pp": "2000",
    "repulse_k_pw": "500",
    "repulse_use_mass": "0",
    "repulse_dvmax": "0.2",
    "stop_vrms": "5e-6",
    "stop_vmax": "2e-5",
    "stop_sleep_frac": "0.95",
    "stop_check_interval": "500",
    "stop_checks_required": "10",
    "inject_vx": "0.0",
    "inject_vy": "0.0",
    "inject_vz": "-0.05",
    "fill_time": "8.0",
    "ram_start": "0.0",
    "ram_duration": "0.0",
    "ram_speed": "0.0",
    "vtk_interval": "1000",
    "vtk_domain_interval": "0",
    "vtk_domain_segments": "96",
}

CASE_MAP = {
    "diameter_scale_factor": "diameter_scale_factor",
    "PF_value": "phi_target",
    "f_La": "f_la",
    "f_Sr": "f_sr",
    "f_Fe": "f_fe",
    "f_Co": "f_co",
}


@dataclass
class Case:
    run_id: str
    folder_name: str
    csv_row: Dict[str, str]
    flags: Dict[str, str]


def clean_cell(value: Optional[str]) -> str:
    return "" if value is None else value.strip()


def normalize_numeric_string(value: str) -> str:
    value = clean_cell(value)
    if not value:
        raise ValueError("Missing numeric value")
    # Keep original scientific notation / formatting as much as possible.
    return value


def build_case(row: Dict[str, str]) -> Case:
    run_raw = clean_cell(row.get("Run"))
    if not run_raw:
        raise ValueError("CSV row is missing Run")

    try:
        run_num = int(float(run_raw))
    except ValueError as exc:
        raise ValueError(f"Invalid Run value: {run_raw}") from exc

    flags = dict(BASE_FLAGS)
    for csv_key, cli_key in CASE_MAP.items():
        value = clean_cell(row.get(csv_key))
        if not value:
            raise ValueError(f"Run {run_num}: missing required column {csv_key}")
        flags[cli_key] = normalize_numeric_string(value)

    folder_name = f"run_{run_num:03d}"
    return Case(run_id=str(run_num), folder_name=folder_name, csv_row=row, flags=flags)


def build_command(exe_path: Path, flags: Dict[str, str]) -> List[str]:
    cmd = [str(exe_path)]
    for key, value in flags.items():
        if value == "":
            continue
        cmd.extend([f"--{key}", value])
    return cmd


def windows_quote(arg: str) -> str:
    return subprocess.list2cmdline([arg])


def command_to_text(cmd: List[str]) -> str:
    return subprocess.list2cmdline(cmd)


def find_latest_atoms(case_dir: Path) -> Optional[Path]:
    atoms = sorted(case_dir.glob("atoms_*.xyz"))
    if not atoms:
        return None

    def iter_key(path: Path) -> int:
        stem = path.stem
        try:
            return int(stem.split("_")[-1])
        except Exception:
            return -1

    atoms.sort(key=iter_key)
    return atoms[-1]


def maybe_run_post(case_dir: Path, base_dir: Path, flags: Dict[str, str], python_cmd: str) -> None:
    stats_script = base_dir / "_fill_stats.py"
    plot_script = base_dir / "_atoms_plot_all.py"

    latest_atoms = find_latest_atoms(case_dir)
    if stats_script.exists() and latest_atoms is not None:
        stats_cmd = [
            python_cmd,
            str(stats_script),
            "--rin", flags["rin"],
            "--rout", flags["rout"],
            "--length", flags["length"],
            "--rbins", "100",
            "--zbins", "100",
            "--out", "stats.csv",
            str(latest_atoms.name),
        ]
        subprocess.run(stats_cmd, cwd=case_dir, check=False)

    if plot_script.exists():
        plot_cmd = [python_cmd, str(plot_script)]
        subprocess.run(plot_cmd, cwd=case_dir, check=False)


def write_case_files(case_dir: Path, case: Case, exe_path: Path) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "run_id": case.run_id,
        "folder_name": case.folder_name,
        "csv_row": case.csv_row,
        "solver_flags": case.flags,
    }
    (case_dir / "case_params.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    cmd = build_command(exe_path, case.flags)
    (case_dir / "command.txt").write_text(command_to_text(cmd) + "\n", encoding="utf-8")

    bat_lines = [
        "@echo off",
        "setlocal",
        f'cd /d "%~dp0"',
        command_to_text(cmd),
        "set ERR=%ERRORLEVEL%",
        "if not %ERR%==0 exit /b %ERR%",
        "echo Done.",
    ]
    (case_dir / "run_case.bat").write_text("\r\n".join(bat_lines) + "\r\n", encoding="utf-8")


def write_run_all(case_root: Path, case_folders: List[str]) -> None:
    lines = ["@echo off", "setlocal"]
    for folder in case_folders:
        lines.append(f'call "{folder}\\run_case.bat"')
        lines.append("if errorlevel 1 exit /b %ERRORLEVEL%")
    lines.append("echo All cases completed.")
    (case_root / "run_all_cases.bat").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Taguchi case folders and optionally run them.")
    parser.add_argument("--csv", default="taguchi_map.csv", help="Path to the Taguchi CSV file.")
    parser.add_argument("--exe", default=r"..\src\coax_pack_cpu.exe", help="Path to coax_pack_cpu.exe.")
    parser.add_argument("--case-root", default="cases", help="Directory where case folders will be created.")
    parser.add_argument("--base-dir", default=".", help="Working directory that contains the CSV, helper scripts, and relative exe path.")
    parser.add_argument("--python-cmd", default="py", help="Python launcher for optional postprocessing on Windows. Example: py or python.")
    parser.add_argument("--execute", action="store_true", help="Run each case after creating its folder.")
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing case folder before regenerating it.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    csv_path = (base_dir / args.csv).resolve() if not Path(args.csv).is_absolute() else Path(args.csv)
    exe_path = (base_dir / args.exe).resolve() if not Path(args.exe).is_absolute() else Path(args.exe)
    case_root = (base_dir / args.case_root).resolve() if not Path(args.case_root).is_absolute() else Path(args.case_root)

    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 1

    if args.execute and not exe_path.exists():
        print(f"ERROR: executable not found: {exe_path}", file=sys.stderr)
        return 1

    case_root.mkdir(parents=True, exist_ok=True)

    cases: List[Case] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {k: clean_cell(v) for k, v in row.items() if k is not None and clean_cell(k)}
            if not any(cleaned.values()):
                continue
            cases.append(build_case(cleaned))

    if not cases:
        print("ERROR: no valid cases found in CSV", file=sys.stderr)
        return 1

    manifest_rows: List[Dict[str, str]] = []
    case_folders: List[str] = []

    for case in cases:
        case_dir = case_root / case.folder_name
        if case_dir.exists() and args.overwrite:
            shutil.rmtree(case_dir)
        elif case_dir.exists() and not args.overwrite:
            print(f"Skipping existing case folder: {case_dir}")
            manifest_rows.append({
                "Run": case.run_id,
                "CaseFolder": str(case_dir),
                "Status": "skipped_existing",
            })
            case_folders.append(case.folder_name)
            continue

        write_case_files(case_dir, case, exe_path)
        case_folders.append(case.folder_name)

        status = "generated"
        return_code = ""

        if args.execute:
            cmd = build_command(exe_path, case.flags)
            print(f"Running case {case.run_id} in {case_dir}...")
            result = subprocess.run(cmd, cwd=case_dir, check=False)
            return_code = str(result.returncode)
            status = "completed" if result.returncode == 0 else "failed"
            if result.returncode == 0:
                maybe_run_post(case_dir, base_dir, case.flags, args.python_cmd)

        manifest_rows.append({
            "Run": case.run_id,
            "CaseFolder": str(case_dir),
            "DiameterScale": case.flags["diameter_scale_factor"],
            "PackingFactor": case.flags["phi_target"],
            "f_La": case.flags["f_la"],
            "f_Sr": case.flags["f_sr"],
            "f_Fe": case.flags["f_fe"],
            "f_Co": case.flags["f_co"],
            "Status": status,
            "ReturnCode": return_code,
        })

    write_run_all(case_root, case_folders)

    manifest_path = case_root / "manifest.csv"
    fieldnames = [
        "Run", "CaseFolder", "DiameterScale", "PackingFactor",
        "f_La", "f_Sr", "f_Fe", "f_Co", "Status", "ReturnCode",
    ]
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"Wrote {len(cases)} case definitions under: {case_root}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
