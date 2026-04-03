# Coaxial Fill DEM (CPU)

3D hard-sphere DEM-style packing in a coaxial annulus with gravity-driven filling, multi-type particle size distributions, optional shaking, optional wall spring contacts, optional repulsion, and an optional top ram stage.

The solver is centered around [`src/coax_pack_cpu.cpp`](src/coax_pack_cpu.cpp). Around that core, the repository includes batch runners, parameter-sweep tooling, post-processing scripts, and verification utilities for Taguchi studies.

## Recent Improvements

- Adaptive composition control now uses instantaneous per-species injected volume to steer deposition toward the requested final occupied-volume fractions.
- A new solver flag, `--adaptive_composition 0|1`, lets you switch between the new feedback-controlled mode and the legacy fixed inlet sampling behavior.
- `testing_map/verify_taguchi_cases.py` verifies each completed Taguchi case against the requested packing factor, species volume fractions, and diameter scale factor.
- `testing_map/run_verify_taguchi_cases.bat` provides a direct Windows entry point for the verifier.
- Verification outputs now include `verification_report.csv`, `verification_summary.txt`, and a `success_xyz/` folder containing the last XYZ file from each passing case.

## Features

- Annular domain with inner wall, outer wall, bottom plane, and optional top ram
- Gravity-driven particle injection from the top of the column
- Four material types with independent size distributions and optional per-type density
- Adaptive composition controller for matching target occupied-volume fractions
- Diameter scaling for parametric studies
- Normal restitution and tangential damping
- Cushion-radius collision inflation
- Optional wall spring-damper contact model
- Optional multi-axis shaking
- Optional short-range repulsion to improve spreading
- Early-stop criteria after reaching `phi_target`
- XYZ and VTK output for analysis and visualization
- Taguchi case generation and verification workflow

## Repository Layout

- `src/coax_pack_cpu.cpp`: main CPU solver
- `src/_compile_win.bat`: Windows build helper
- `testing/_run_win_cpu.bat`: single-run Windows workflow
- `testing/_fill_stats.py`: simple radial and axial analysis from one XYZ snapshot
- `testing/_atoms_plot_all.py`: frame visualization and animation helper
- `testing_map/run_taguchi_matrix.py`: creates and optionally executes multi-case studies
- `testing_map/taguchi_map.csv`: Taguchi input table
- `testing_map/verify_taguchi_cases.py`: verifies finished case folders against Taguchi targets
- `testing_map/run_verify_taguchi_cases.bat`: Windows wrapper for verification
- `testing_map/cases/`: generated case folders and outputs

## Build

### Linux / macOS

```bash
g++ -O3 -march=native -fopenmp -std=c++17 -o coax_pack_cpu coax_pack_cpu.cpp
```

### Windows (MSVC)

From `src/`:

```bat
_compile_win.bat
```

Or directly:

```bat
cl /EHsc /O2 /openmp:llvm /std:c++17 /Fe:coax_pack_cpu.exe coax_pack_cpu.cpp
```

## Core Solver Controls

These are the most important physical and workflow flags:

- `--natoms_max`: maximum number of injected particles
- `--dt`: time step in seconds
- `--niter`: number of time steps
- `--dump_interval`: base output interval
- `--rin`, `--rout`, `--length`: annulus geometry
- `--flux`: particle injection rate
- `--gravity`: gravity magnitude
- `--fill_time`: injection duration
- `--phi_target`: stop-filling target based on occupied volume fraction
- `--f_la`, `--f_sr`, `--f_fe`, `--f_co`: requested species targets
- `--diameter_scale_factor`: multiplier applied to sampled diameters
- `--adaptive_composition 0|1`: enable or disable feedback-controlled composition steering

## Composition Control

The requested composition fractions are stored in the order:

```text
{La, Sr, Fe, Co}
```

Current default behavior is:

- `--adaptive_composition 1` by default
- the solver tracks injected occupied volume by species
- when `phi_target` is active, injection is biased toward the species that is currently below its requested occupied-volume target
- if adaptive control is disabled, the code falls back to legacy fixed-probability inlet sampling

Important nuance:

- The adaptive controller steers the mixture toward the requested final metrics
- It does not mathematically guarantee an exact match because the process is still stochastic and particle sizes vary by species
- Verification after the run is still recommended

## Recommended Workflows

### Single Run

Use:

```bat
testing\_run_win_cpu.bat
```

This is the best entry point for interactive solver tuning and quick experiments.

### Taguchi Study

1. Edit `testing_map/taguchi_map.csv`
2. Generate case folders with:

```bat
cd testing_map
_run_taguchi_matrix.bat
```

3. Run the cases:

```bat
cases\run_all_cases.bat
```

4. Verify the outputs:

```bat
run_verify_taguchi_cases.bat
```

## Verification Workflow

The verifier reads each Taguchi row, inspects the corresponding `cases/run_###` folder, finds the last `atoms_*.xyz`, and checks:

- configured case parameters vs. `taguchi_map.csv`
- final occupied packing fraction vs. `PF_value`
- final species occupied-volume fractions vs. `f_La`, `f_Sr`, `f_Fe`, `f_Co`
- inferred diameter scale factor vs. `diameter_scale_factor`

Outputs:

- `testing_map/verification_report.csv`: per-case pass/fail table with observed metrics
- `testing_map/verification_summary.txt`: quick summary of the run
- `testing_map/success_xyz/`: copies of the last XYZ file for each passing case

## Output Files

- `atoms_<iter>.xyz`: element symbol, `x`, `y`, `z`, and particle diameter (`2*r`)
- `atom.<iter>.vtk`: VTK particle output with radius, type ID, and element label
- stdout: iteration, time, and packing-fraction progress

For ParaView:

- open `atom.<iter>.vtk`
- apply `Glyph (Sphere)`
- scale by radius field `r`
- color by type, velocity, or position

## Folder Structure

```text
testing_map/
  taguchi_map.csv
  run_taguchi_matrix.py
  verify_taguchi_cases.py
  run_verify_taguchi_cases.bat
  verification_report.csv
  verification_summary.txt
  success_xyz/
  cases/
    manifest.csv
    run_all_cases.bat
    run_001/
      case_params.json
      command.txt
      run_case.bat
      atoms_*.xyz
      atom.*.vtk
```

## Tips

- Start with small particle counts and short runs before launching large sweeps
- Keep `debug` on while tuning new physics settings
- Use `phi_target` together with adaptive composition control for composition-sensitive studies
- Verify completed studies instead of assuming the requested metrics were achieved
- Treat the final column of `atoms_*.xyz` as diameter, not radius

## License

Free as in beer.
