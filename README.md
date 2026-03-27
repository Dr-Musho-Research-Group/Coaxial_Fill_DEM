# Coaxial Fill DEM (CPU)

3D hard-sphere DEM-style packing in a coaxial (annular) column with gravity-driven filling, optional multi-axis shaking, cushion radius support, enhanced wall spring contacts, and an optional top ram stage.

The solver uses a cell-linked neighbor search, impulse-based sphere-sphere collisions, optional spring-damper wall contacts, and damping for realistic settling behavior.

This version extends the original code with:
- Taguchi test matrix automation
- Composition control (La, Sr, Fe, Co)
- Diameter scaling
- Structured batch execution
- ParaView visualization workflow

---

## Features

- Annular domain: inner and outer cylindrical walls with finite height L
- Gravity-driven particle injection
- Multi-type particle size distributions
- Composition-controlled material fractions
- Diameter scaling for parametric studies
- Normal restitution and tangential damping
- Cushion radius support
- Wall spring-damper model
- Multi-axis shaking (x, y, z)
- Optional top ram stage
- Automated Taguchi case generation
- VTK + XYZ outputs for visualization

---

## Build Instructions

### Linux / macOS

```
g++ -O3 -march=native -fopenmp -std=c++17 -o coax_pack_cpu coax_pack_cpu.cpp
```

### Windows (MSVC)

```
cl /O2 /openmp /std:c++17 coax_pack_cpu.cpp /Fe:coax_pack_cpu.exe
```

---

## Core Solver Parameters (Original)

These are the primary physical controls of the solver:

1  natoms_max     Total particles  
2  dt             Time step  
3  niter          Number of steps  
4  dump_interval  Output frequency  
5  debug          Debug flag  
6  seed           RNG seed  
7  Rin            Inner radius  
8  Rout           Outer radius  
9  L              Column height  
10 flux           Injection rate  
11 g              Gravity  
12 shake_hz       Shake frequency  
13 shake_amp      Legacy shake amplitude  
14 fill_time      Injection duration  
15 ram_start      Ram start time  
16 ram_duration   Ram duration  
17 ram_speed      Ram speed  
18 VF             Target volume fraction  

---

## New Parameters

### Diameter Scaling

```
--diameter_scale_factor <value>
```

Scales all particle diameters.

---

### Composition Fractions

```
--f_la <value>
--f_sr <value>
--f_fe <value>
--f_co <value>
```

Order:
```
{La, Sr, Fe, Co}
```

Fractions are normalized internally.

---

### Packing Factor

```
--phi_target <value>
```

---

## Taguchi Workflow (Recommended)

### 1. Create CSV

```
Run,diameter_scale_factor,PF_value,f_La,f_Sr,f_Fe,f_Co
1,1.0,0.55,0.45,0.20,0.30,0.05
```

---

### 2. Generate Cases

```
_run_taguchi_matrix.bat
```

---

### 3. Run All Cases

```
cases\run_all_cases.bat
```

---

## Folder Structure

```
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

---

## Output Files (Original)

- atoms_<iter>.xyz → particle positions and radius  
- atom.<iter>.vtk → VTK visualization  
- stdout → iteration, time, packing fraction  

---

## ParaView Visualization

Open:

```
atom.<iter>.vtk
```

### Recommended Workflow

- Apply Glyph (Sphere)
- Scale by radius `r`
- Color by velocity or position
- Use Slice or Clip filters
- Animate timesteps

---

## Student Workflow

1. Edit CSV  
2. Run generator  
3. Run simulations  
4. Visualize in ParaView  
5. Analyze using manifest.csv  

---

## Tips

- Start with small particle counts
- Use debug mode
- Verify packing with XYZ output

---

## License

Free as in beer.
