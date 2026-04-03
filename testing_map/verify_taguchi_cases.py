#!/usr/bin/env python3
"""
Verify generated Taguchi cases against taguchi_map.csv and final XYZ outputs.

Checks performed for each run:
  1. The generated case metadata matches the Taguchi CSV targets.
  2. The final XYZ file exists.
  3. The final packed volume fraction matches PF_value within tolerance.
  4. The final species occupied-volume fractions match f_La/f_Sr/f_Fe/f_Co within tolerance.
  5. The realized diameter scale factor inferred from the final XYZ matches the requested
     diameter_scale_factor within tolerance.

Outputs:
  - verification_report.csv
  - verification_summary.txt
  - success_xyz/<run_folder>_final.xyz copies for passing cases

This script uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ELEM_ORDER = ["La", "Sr", "Fe", "Co"]
SOURCE_LABELS = {
    "La": "La2O3",
    "Sr": "SrO",
    "Fe": "Fe2O3",
    "Co": "Co3O4",
}


@dataclass
class CaseExpectation:
    run_id: str
    folder_name: str
    diameter_scale_factor: float
    phi_target: float
    fractions: Dict[str, float]


@dataclass
class ParticleStats:
    particle_count: int
    total_particle_volume: float
    packing_fraction: float
    species_counts: Dict[str, int]
    species_volume_fraction: Dict[str, float]
    inferred_scale_factor: Optional[float]
    xyz_path: Optional[Path]


def clean_cell(value: Optional[str]) -> str:
    return "" if value is None else value.strip()


def load_taguchi_cases(csv_path: Path) -> List[CaseExpectation]:
    cases: List[CaseExpectation] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            run_raw = clean_cell(row.get("Run"))
            if not run_raw:
                continue
            run_num = int(float(run_raw))
            folder_name = f"run_{run_num:03d}"
            fractions = {
                "La": float(clean_cell(row.get("f_La"))),
                "Sr": float(clean_cell(row.get("f_Sr"))),
                "Fe": float(clean_cell(row.get("f_Fe"))),
                "Co": float(clean_cell(row.get("f_Co"))),
            }
            cases.append(
                CaseExpectation(
                    run_id=str(run_num),
                    folder_name=folder_name,
                    diameter_scale_factor=float(clean_cell(row.get("diameter_scale_factor"))),
                    phi_target=float(clean_cell(row.get("PF_value"))),
                    fractions=fractions,
                )
            )
    return cases


def parse_number_list(block: str) -> List[float]:
    return [float(token) for token in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", block)]


def load_base_mean_radii_from_source(source_path: Path) -> Dict[str, float]:
    text = source_path.read_text(encoding="utf-8")
    means: Dict[str, float] = {}

    for elem, label in SOURCE_LABELS.items():
        label_pat = rf"//{re.escape(label)}\s*g_types\[\d+\]\.diam_um\s*=\s*\{{(.*?)\}};\s*g_types\[\d+\]\.cumu\s*=\s*\{{(.*?)\}};"
        match = re.search(label_pat, text, re.S)
        if not match:
            raise ValueError(f"Could not parse size distribution for {elem} from {source_path}")
        diam_um = parse_number_list(match.group(1))
        cumu = parse_number_list(match.group(2))
        if len(diam_um) != len(cumu) or not diam_um:
            raise ValueError(f"Invalid diameter/cumulative table for {elem}")

        probs: List[float] = []
        prev = 0.0
        for value in cumu:
            probs.append(max(0.0, value - prev))
            prev = value
        if prev < 1.0:
            probs[-1] += 1.0 - prev

        mean_diam_m = sum(d * p for d, p in zip(diam_um, probs)) * 1e-6
        means[elem] = 0.5 * mean_diam_m

    return means


def load_case_params(case_dir: Path) -> Dict[str, object]:
    case_json = case_dir / "case_params.json"
    if not case_json.exists():
        return {}
    return json.loads(case_json.read_text(encoding="utf-8"))


def find_latest_xyz(case_dir: Path) -> Optional[Path]:
    best: Optional[Tuple[int, Path]] = None
    for path in case_dir.glob("atoms_*.xyz"):
        match = re.fullmatch(r"atoms_(\d+)\.xyz", path.name)
        if not match:
            continue
        step = int(match.group(1))
        if best is None or step > best[0]:
            best = (step, path)
    return None if best is None else best[1]


def compute_particle_stats(
    xyz_path: Optional[Path],
    rin: float,
    rout: float,
    length: float,
    base_mean_radii: Dict[str, float],
) -> ParticleStats:
    if xyz_path is None or not xyz_path.exists():
        return ParticleStats(
            particle_count=0,
            total_particle_volume=0.0,
            packing_fraction=math.nan,
            species_counts={elem: 0 for elem in ELEM_ORDER},
            species_volume_fraction={elem: math.nan for elem in ELEM_ORDER},
            inferred_scale_factor=None,
            xyz_path=xyz_path,
        )

    species_counts = {elem: 0 for elem in ELEM_ORDER}
    species_volumes = {elem: 0.0 for elem in ELEM_ORDER}
    species_radii_sum = {elem: 0.0 for elem in ELEM_ORDER}

    with xyz_path.open("r", encoding="utf-8") as handle:
        first_line = handle.readline().strip()
        declared_count = int(first_line) if first_line else 0
        handle.readline()
        parsed_count = 0

        for line in handle:
            parts = line.split()
            if len(parts) < 5:
                continue
            elem = parts[0]
            if elem not in species_counts:
                continue
            diameter = float(parts[4])
            radius = 0.5 * diameter
            species_counts[elem] += 1
            species_radii_sum[elem] += radius
            species_volumes[elem] += (4.0 / 3.0) * math.pi * radius ** 3
            parsed_count += 1

    particle_count = parsed_count if parsed_count else declared_count
    total_particle_volume = sum(species_volumes.values())
    domain_volume = math.pi * (rout ** 2 - rin ** 2) * length
    packing_fraction = total_particle_volume / domain_volume if domain_volume > 0.0 else math.nan

    if total_particle_volume > 0.0:
        species_volume_fraction = {
            elem: species_volumes[elem] / total_particle_volume for elem in ELEM_ORDER
        }
    else:
        species_volume_fraction = {elem: math.nan for elem in ELEM_ORDER}

    inferred_factors: List[float] = []
    total_weight = 0
    for elem in ELEM_ORDER:
        count = species_counts[elem]
        base_mean = base_mean_radii[elem]
        if count <= 0 or base_mean <= 0.0:
            continue
        mean_radius = species_radii_sum[elem] / count
        inferred_factors.append(mean_radius / base_mean * count)
        total_weight += count
    inferred_scale_factor = None
    if total_weight > 0:
        inferred_scale_factor = sum(inferred_factors) / total_weight

    return ParticleStats(
        particle_count=particle_count,
        total_particle_volume=total_particle_volume,
        packing_fraction=packing_fraction,
        species_counts=species_counts,
        species_volume_fraction=species_volume_fraction,
        inferred_scale_factor=inferred_scale_factor,
        xyz_path=xyz_path,
    )


def float_close(a: float, b: float, tol: float) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Taguchi case outputs against CSV targets.")
    parser.add_argument("--csv", default="taguchi_map.csv", help="Path to Taguchi CSV input.")
    parser.add_argument("--cases", default="cases", help="Directory containing run_### case folders.")
    parser.add_argument("--source", default=r"..\src\coax_pack_cpu.cpp", help="Path to solver source for base size distributions.")
    parser.add_argument("--pf-tol", type=float, default=0.02, help="Absolute tolerance for final packing fraction.")
    parser.add_argument("--species-tol", type=float, default=0.08, help="Absolute tolerance for species occupied-volume fractions.")
    parser.add_argument("--scale-tol", type=float, default=0.08, help="Absolute tolerance for inferred diameter scale factor.")
    parser.add_argument("--success-dir", default="success_xyz", help="Folder where passing final XYZ files are copied.")
    parser.add_argument("--report-csv", default="verification_report.csv", help="CSV report to write.")
    parser.add_argument("--summary-txt", default="verification_summary.txt", help="Text summary to write.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    csv_path = (base_dir / args.csv).resolve() if not Path(args.csv).is_absolute() else Path(args.csv)
    cases_dir = (base_dir / args.cases).resolve() if not Path(args.cases).is_absolute() else Path(args.cases)
    source_path = (base_dir / args.source).resolve() if not Path(args.source).is_absolute() else Path(args.source)
    success_dir = (base_dir / args.success_dir).resolve() if not Path(args.success_dir).is_absolute() else Path(args.success_dir)
    report_csv = (base_dir / args.report_csv).resolve() if not Path(args.report_csv).is_absolute() else Path(args.report_csv)
    summary_txt = (base_dir / args.summary_txt).resolve() if not Path(args.summary_txt).is_absolute() else Path(args.summary_txt)

    base_mean_radii = load_base_mean_radii_from_source(source_path)
    expectations = load_taguchi_cases(csv_path)

    if success_dir.exists():
        shutil.rmtree(success_dir)
    success_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    success_count = 0

    for expected in expectations:
        case_dir = cases_dir / expected.folder_name
        params = load_case_params(case_dir)
        solver_flags = params.get("solver_flags", {}) if isinstance(params, dict) else {}
        xyz_path = find_latest_xyz(case_dir)

        rin = float(solver_flags.get("rin", "nan")) if solver_flags else math.nan
        rout = float(solver_flags.get("rout", "nan")) if solver_flags else math.nan
        length = float(solver_flags.get("length", "nan")) if solver_flags else math.nan
        stats = compute_particle_stats(xyz_path, rin, rout, length, base_mean_radii)

        config_scale = float(solver_flags.get("diameter_scale_factor", "nan")) if solver_flags else math.nan
        config_phi = float(solver_flags.get("phi_target", "nan")) if solver_flags else math.nan
        config_fracs = {
            "La": float(solver_flags.get("f_la", "nan")) if solver_flags else math.nan,
            "Sr": float(solver_flags.get("f_sr", "nan")) if solver_flags else math.nan,
            "Fe": float(solver_flags.get("f_fe", "nan")) if solver_flags else math.nan,
            "Co": float(solver_flags.get("f_co", "nan")) if solver_flags else math.nan,
        }

        config_match = (
            float_close(config_scale, expected.diameter_scale_factor, 1e-12)
            and float_close(config_phi, expected.phi_target, 1e-12)
            and all(float_close(config_fracs[e], expected.fractions[e], 1e-12) for e in ELEM_ORDER)
        )

        pf_pass = float_close(stats.packing_fraction, expected.phi_target, args.pf_tol)
        scale_pass = (
            stats.inferred_scale_factor is not None
            and float_close(stats.inferred_scale_factor, expected.diameter_scale_factor, args.scale_tol)
        )
        species_passes = {
            elem: float_close(stats.species_volume_fraction[elem], expected.fractions[elem], args.species_tol)
            for elem in ELEM_ORDER
        }
        species_pass = all(species_passes.values())
        xyz_exists = xyz_path is not None and xyz_path.exists()

        pass_all = bool(config_match and xyz_exists and pf_pass and scale_pass and species_pass)

        reasons: List[str] = []
        if not config_match:
            reasons.append("case_params_mismatch")
        if not xyz_exists:
            reasons.append("missing_final_xyz")
        if xyz_exists and not pf_pass:
            reasons.append("packing_fraction_out_of_tolerance")
        if xyz_exists and not scale_pass:
            reasons.append("diameter_scale_out_of_tolerance")
        for elem in ELEM_ORDER:
            if xyz_exists and not species_passes[elem]:
                reasons.append(f"{elem.lower()}_volume_fraction_out_of_tolerance")

        if pass_all and xyz_path is not None:
            success_name = f"{expected.folder_name}_final.xyz"
            shutil.copy2(xyz_path, success_dir / success_name)
            success_count += 1

        row: Dict[str, object] = {
            "Run": expected.run_id,
            "CaseFolder": str(case_dir),
            "LatestXYZ": "" if xyz_path is None else str(xyz_path),
            "Pass": "YES" if pass_all else "NO",
            "FailureReasons": ";".join(reasons),
            "ConfigMatchesTaguchi": "YES" if config_match else "NO",
            "ExpectedDiameterScale": expected.diameter_scale_factor,
            "ConfiguredDiameterScale": config_scale,
            "ObservedDiameterScale": "" if stats.inferred_scale_factor is None else f"{stats.inferred_scale_factor:.8f}",
            "ExpectedPF": expected.phi_target,
            "ObservedPF": "" if not math.isfinite(stats.packing_fraction) else f"{stats.packing_fraction:.8f}",
            "ParticleCount": stats.particle_count,
        }

        for elem in ELEM_ORDER:
            row[f"Expected_{elem}_volfrac"] = expected.fractions[elem]
            value = stats.species_volume_fraction[elem]
            row[f"Observed_{elem}_volfrac"] = "" if not math.isfinite(value) else f"{value:.8f}"
            row[f"{elem}_count"] = stats.species_counts[elem]
            row[f"{elem}_pass"] = "YES" if species_passes[elem] else "NO"

        row["PF_pass"] = "YES" if pf_pass else "NO"
        row["Scale_pass"] = "YES" if scale_pass else "NO"
        rows.append(row)

    fieldnames = list(rows[0].keys()) if rows else [
        "Run", "CaseFolder", "LatestXYZ", "Pass", "FailureReasons"
    ]
    with report_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    failed_count = len(rows) - success_count
    summary_lines = [
        f"CSV source: {csv_path}",
        f"Cases directory: {cases_dir}",
        f"Solver source: {source_path}",
        f"PF tolerance: {args.pf_tol}",
        f"Species tolerance: {args.species_tol}",
        f"Scale tolerance: {args.scale_tol}",
        f"Total cases checked: {len(rows)}",
        f"Passing cases: {success_count}",
        f"Failing cases: {failed_count}",
        f"Success XYZ folder: {success_dir}",
        f"Report CSV: {report_csv}",
    ]
    summary_txt.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"Wrote report: {report_csv}")
    print(f"Wrote summary: {summary_txt}")
    print(f"Copied {success_count} passing XYZ files into: {success_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
