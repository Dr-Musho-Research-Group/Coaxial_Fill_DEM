@echo off
setlocal EnableDelayedExpansion

REM ================================================================
REM  Batch script to run coax_pack_cpu.exe simulation
REM  Uses order-independent --flags (defaults handled in the exe)
REM ================================================================

REM Record start time
for /f "tokens=1-4 delims=:." %%a in ("%TIME%") do (
    set /a START_H=%%a
    set /a START_M=%%b
    set /a START_S=%%c
    set /a START_MS=%%d
)

REM -------------------- User Parameters ---------------------------
set DEBUG_LEVEL=1
set NATOMS_MAX=25000

REM Tuned defaults for Taguchi case 1. These settings reduced wall time
REM substantially relative to the older baseline while still giving
REM intermediate particle VTK dumps for ParaView.
set DT=4e-6
set NITER=120000
set DUMP_INTERVAL=10000
set SEED=42

REM This case is overhead-limited, so the tuned default uses 4 threads.
REM Set THREADS=0 to use the tuned cap automatically.
set THREADS=4
set RECOMMENDED_THREAD_CAP=4
set OMP_MIN_PARTICLES=512

REM Geometry [m]
set RIN=23e-6
set ROUT=39e-6
set LENGTH=379e-6

REM Physics
set FLUX=24000
set GRAVITY=0.0
set SHAKE_FREQ=1000
set SHAKE_AMP=0

REM Independent shake amplitudes [m]
set SHAKE_AMP_X=%SHAKE_AMP%
set SHAKE_AMP_Y=%SHAKE_AMP%
set SHAKE_AMP_Z=0
set SHAKE_XY_LEGACY=0

REM Contact cushion [m] (adds clearance around spheres)
set CUSHION=1E-7

REM Wall spring-damper (set WALL_K=0 to disable)
set WALL_K=0.0
set WALL_ZETA=0.20
set WALL_DVMAX=5.0

REM Wall roughness (set WALL_ROUGH_AMP=0 to disable)
set WALL_ROUGH_AMP=0
set WALL_ROUGH_MTH=8
set WALL_ROUGH_MZ=3

REM Damping / restitution (set LIN_DAMP=0 to disable global damping)
set LIN_DAMP=800.0
REM Extra damping is only added after injection completes to settle faster.
set POST_FILL_LIN_DAMP=1500.0
set E_PP=0.20
set E_PW=0.15
set TANGENT_DAMP=0.90

REM Short-range repulsion (set REPULSE_RANGE=0 to disable)
set REPULSE_RANGE=0.5e-5
set REPULSE_K_PP=2000
set REPULSE_K_PW=500
set REPULSE_USE_MASS=0
set REPULSE_DVMAX=0.2

REM Early-stop after phi_target is reached. Sleep fraction is disabled here
REM because the solver rarely marks enough particles asleep in this workflow.
set STOP_VRMS=0.006
set STOP_VMAX=0.12
set STOP_SLEEP_FRAC=0.0
set STOP_CHECK_INTERVAL=1000
set STOP_CHECKS_REQUIRED=2

REM Injection initial velocity [m/s]
set INJECT_VX=0.0
set INJECT_VY=0.0
set INJECT_VZ=-0.04

REM Process stages [s]
set FILL_TIME=8.0
set RAM_START=0.0
set RAM_DURATION=0.0
set RAM_SPEED=0.0

REM Taguchi case 1 target
set VF=0.35
set DIAMETER_SCALE_FACTOR=0.9
set F_LA=0.10
set F_SR=0.10
set F_FE=0.70
set F_CO=0.10
set ADAPTIVE_COMPOSITION=1

REM Output frequency control
REM Note: vtk_interval controls particle VTK frequency
REM       vtk_domain_interval controls domain surface VTK frequency
set XYZ_INTERVAL=0
set VTK_INTERVAL=%DUMP_INTERVAL%
set VTK_DOMAIN_INTERVAL=0
set VTK_DOMAIN_SEGMENTS=96
set DUMP_FINAL_XYZ=1
set DUMP_FINAL_VTK=1
set SOLVER_LOG=solver_output.log
REM ----------------------------------------------------------------

cd /d "%~dp0"

REM Auto thread count if requested.
if "%THREADS%"=="0" (
    set THREADS=%RECOMMENDED_THREAD_CAP%
)
if %THREADS% GTR %NUMBER_OF_PROCESSORS% (
    set THREADS=%NUMBER_OF_PROCESSORS%
)
set OMP_NUM_THREADS=%THREADS%
set OMP_THREAD_LIMIT=%THREADS%

echo ===============================================================
echo Cleaning previous output files...
del *.xyz >nul 2>&1
del *.dat >nul 2>&1
del *.vtk >nul 2>&1
del *.png >nul 2>&1
del *.mp4 >nul 2>&1
del *.csv >nul 2>&1
del "%SOLVER_LOG%" >nul 2>&1
echo ===============================================================

echo Running coax_pack_cpu.exe ...
echo Parameters:
echo   NATOMS_MAX             = %NATOMS_MAX%
echo   DT                     = %DT%
echo   NITER                  = %NITER%
echo   DUMP_INTERVAL          = %DUMP_INTERVAL%
echo   DEBUG_LEVEL            = %DEBUG_LEVEL%
echo   SEED                   = %SEED%
echo   THREADS                = %THREADS%
echo   THREAD CAP             = %RECOMMENDED_THREAD_CAP% (auto mode)
echo   OMP_MIN_PARTICLES      = %OMP_MIN_PARTICLES%
echo   Rin, Rout, L           = %RIN%, %ROUT%, %LENGTH%
echo   Flux                   = %FLUX%
echo   Gravity                = %GRAVITY%
echo   Shake (Hz)             = %SHAKE_FREQ%
echo   Shake amps (x,y,z)     = %SHAKE_AMP_X%, %SHAKE_AMP_Y%, %SHAKE_AMP_Z% (legacy_xy=%SHAKE_XY_LEGACY%)
echo   Fill/Ram               = %FILL_TIME%s / %RAM_START%s to %RAM_DURATION%s @ %RAM_SPEED%m/s
echo   VF Target              = %VF%
echo   Diameter scale         = %DIAMETER_SCALE_FACTOR%
echo   Fractions (La,Sr,Fe,Co)= %F_LA%, %F_SR%, %F_FE%, %F_CO%
echo   Adaptive composition   = %ADAPTIVE_COMPOSITION%
echo   Cushion                = %CUSHION%
echo   Wall spring (k,zeta,dvmax) = %WALL_K%, %WALL_ZETA%, %WALL_DVMAX%
echo   Damping (lin,post_fill,e_pp,e_pw,tangent) = %LIN_DAMP%, %POST_FILL_LIN_DAMP%, %E_PP%, %E_PW%, %TANGENT_DAMP%
echo   Repulsion (range,k_pp,k_pw) = %REPULSE_RANGE%, %REPULSE_K_PP%, %REPULSE_K_PW%
echo   Early-stop (vrms,vmax,sleep_frac) = %STOP_VRMS%, %STOP_VMAX%, %STOP_SLEEP_FRAC% (check=%STOP_CHECK_INTERVAL%, req=%STOP_CHECKS_REQUIRED%)
echo   Inject v0 (x,y,z)      = %INJECT_VX%, %INJECT_VY%, %INJECT_VZ%
echo   Solver log             = %SOLVER_LOG%
echo   Final dumps (xyz,vtk)  = %DUMP_FINAL_XYZ%, %DUMP_FINAL_VTK%
echo   VTK_INTERVAL           = %VTK_INTERVAL%
echo   VTK_DOMAIN_INTERVAL    = %VTK_DOMAIN_INTERVAL%
echo ===============================================================

REM -------------------- Run the executable ------------------------
set EXE=..\src\coax_pack_cpu.exe

"%EXE%" ^
  --natoms_max %NATOMS_MAX% ^
  --dt %DT% ^
  --niter %NITER% ^
  --dump_interval %DUMP_INTERVAL% ^
  --debug %DEBUG_LEVEL% ^
  --seed %SEED% ^
  --threads %THREADS% ^
  --omp_min_particles %OMP_MIN_PARTICLES% ^
  --rin %RIN% ^
  --rout %ROUT% ^
  --length %LENGTH% ^
  --flux %FLUX% ^
  --gravity %GRAVITY% ^
  --shake_hz %SHAKE_FREQ% ^
  --shake_amp %SHAKE_AMP_Z% ^
  --shake_amp_x %SHAKE_AMP_X% ^
  --shake_amp_y %SHAKE_AMP_Y% ^
  --shake_amp_z %SHAKE_AMP_Z% ^
  --shake_xy_legacy %SHAKE_XY_LEGACY% ^
  --cushion %CUSHION% ^
  --wall_k %WALL_K% ^
  --wall_zeta %WALL_ZETA% ^
  --wall_dvmax %WALL_DVMAX% ^
  --wall_rough_amp %WALL_ROUGH_AMP% ^
  --wall_rough_mth %WALL_ROUGH_MTH% ^
  --wall_rough_mz %WALL_ROUGH_MZ% ^
  --lin_damp %LIN_DAMP% ^
  --post_fill_lin_damp %POST_FILL_LIN_DAMP% ^
  --e_pp %E_PP% ^
  --e_pw %E_PW% ^
  --tangent_damp %TANGENT_DAMP% ^
  --repulse_range %REPULSE_RANGE% ^
  --repulse_k_pp %REPULSE_K_PP% ^
  --repulse_k_pw %REPULSE_K_PW% ^
  --repulse_use_mass %REPULSE_USE_MASS% ^
  --repulse_dvmax %REPULSE_DVMAX% ^
  --stop_vrms %STOP_VRMS% ^
  --stop_vmax %STOP_VMAX% ^
  --stop_sleep_frac %STOP_SLEEP_FRAC% ^
  --stop_check_interval %STOP_CHECK_INTERVAL% ^
  --stop_checks_required %STOP_CHECKS_REQUIRED% ^
  --inject_vx %INJECT_VX% ^
  --inject_vy %INJECT_VY% ^
  --inject_vz %INJECT_VZ% ^
  --fill_time %FILL_TIME% ^
  --ram_start %RAM_START% ^
  --ram_duration %RAM_DURATION% ^
  --ram_speed %RAM_SPEED% ^
  --phi_target %VF% ^
  --diameter_scale_factor %DIAMETER_SCALE_FACTOR% ^
  --f_la %F_LA% ^
  --f_sr %F_SR% ^
  --f_fe %F_FE% ^
  --f_co %F_CO% ^
  --adaptive_composition %ADAPTIVE_COMPOSITION% ^
  --log_file %SOLVER_LOG% ^
  --xyz_interval %XYZ_INTERVAL% ^
  --vtk_interval %VTK_INTERVAL% ^
  --vtk_domain_interval %VTK_DOMAIN_INTERVAL% ^
  --vtk_domain_segments %VTK_DOMAIN_SEGMENTS% ^
  --dump_final_xyz %DUMP_FINAL_XYZ% ^
  --dump_final_vtk %DUMP_FINAL_VTK%
set "SOLVER_RC=%ERRORLEVEL%"

REM -------------------- Timing and Status -------------------------
for /f "tokens=1-4 delims=:." %%a in ("%TIME%") do (
    set /a END_H=%%a
    set /a END_M=%%b
    set /a END_S=%%c
    set /a END_MS=%%d
)

timeout /t 1 /nobreak >nul

set /a START_TOTAL_MS=(%START_H%*3600000)+(%START_M%*60000)+(%START_S%*1000)+%START_MS%
set /a END_TOTAL_MS=(%END_H%*3600000)+(%END_M%*60000)+(%END_S%*1000)+%END_MS%
set /a ELAPSED_MS=%END_TOTAL_MS% - %START_TOTAL_MS%
set /a ELAPSED_SEC=%ELAPSED_MS% / 1000
set /a ELAPSED_MS_REMAINDER=%ELAPSED_MS% %% 1000

echo ===============================================================
echo Simulation completed in %ELAPSED_SEC%.%ELAPSED_MS_REMAINDER% seconds.

if "%SOLVER_RC%"=="0" (
    echo Simulation completed successfully!
) else (
    echo Simulation failed! Error code: %SOLVER_RC%
    pause
    exit /b %SOLVER_RC%
)
echo ===============================================================

REM -------------------- Postprocessing ----------------------------
echo Renaming output files...
rename "output_step_*.xyz" "atoms_*.xyz" >nul 2>&1

set FINAL_XYZ=
set FINAL_STEP=-1
for %%F in (atoms_*.xyz) do (
    set "FINAL_NAME=%%~nF"
    set "FINAL_STEP_CAND=!FINAL_NAME:atoms_=!"
    set /a FINAL_STEP_NUM=!FINAL_STEP_CAND! 2>nul
    if !FINAL_STEP_NUM! GTR !FINAL_STEP! (
        set /a FINAL_STEP=!FINAL_STEP_NUM!
        set "FINAL_XYZ=%%F"
    )
)

if defined FINAL_XYZ (
    echo Final XYZ detected: %FINAL_XYZ%
    echo Final particle VTK expected near atom.%FINAL_STEP%.vtk
) else (
    echo (No atoms_*.xyz file detected.)
)

echo Running Python stat script if available...
if exist "_fill_stats.py" (
    if defined FINAL_XYZ (
        call :run_fill_stats "%FINAL_XYZ%"
    ) else (
        echo (No final XYZ found, skipping stats.)
    )
) else (
    echo (_fill_stats.py not found, skipping stats.)
)

echo Running Python plot script if available...
if exist "_atoms_plot_all.py" (
    call :run_plot_script
) else (
    echo (No plot script found, skipping.)
)

echo ===============================================================
echo Process complete!
pause
exit /b 0

:run_fill_stats
set "TARGET_XYZ=%~1"
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python _fill_stats.py ^
        --rin %RIN% ^
        --rout %ROUT% ^
        --length %LENGTH% ^
        --rbins 100 ^
        --zbins 100 ^
        --out fill_stats ^
        "%TARGET_XYZ%"
    if %ERRORLEVEL%==0 goto :eof
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py _fill_stats.py ^
        --rin %RIN% ^
        --rout %ROUT% ^
        --length %LENGTH% ^
        --rbins 100 ^
        --zbins 100 ^
        --out fill_stats ^
        "%TARGET_XYZ%"
    if %ERRORLEVEL%==0 goto :eof
)

echo (No Python interpreter with numpy/pandas/matplotlib support was found for _fill_stats.py.)
goto :eof

:run_plot_script
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python _atoms_plot_all.py
    if %ERRORLEVEL%==0 goto :eof
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py _atoms_plot_all.py
    if %ERRORLEVEL%==0 goto :eof
)

echo (No Python interpreter with numpy/matplotlib support was found for _atoms_plot_all.py.)
goto :eof
