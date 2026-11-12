# Wavepacket

Source-available for non-commercial use under [PolyForm Noncommercial 1.0.0](LICENSE). See [LICENSING.md](LICENSING.md).

This code-only snapshot includes source, unexecuted notebooks and static
interface assets. It supplies no saved runs, historical validation results,
study outputs or runtime data. Generate and assess new evidence locally.

A local 1D and 2D quantum dynamics laboratory for evolving wavefunctions,
comparing numerical methods and measuring their errors. One Python engine powers
the browser interface, CLI and four research notebooks.

The model is single-particle, linear Schrödinger evolution under static
potentials. Sixteen experiment families cover free packets, oscillators,
barriers, double wells, interference, diffraction, obstacles and a bent
finite-wall waveguide. The interface provides density, phase, signed current,
diagnostics, replay, comparisons and saved-data export. CPU execution requires
no GPU, account, API key or paid service. Initial installation needs network
access; simulations and the built interface run locally afterward.

## Install and launch

Source development requires **Python 3.12** and **Node.js 24** with npm. Python
dependencies are pinned in [requirements-lock.txt](requirements-lock.txt), and
frontend dependencies in [frontend/package-lock.json](frontend/package-lock.json).
Use a dedicated environment for this project.

On Windows, run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
.venv\Scripts\wavepacket.exe doctor
.venv\Scripts\wavepacket.exe serve --open-browser
```

Pass `-Python C:\path\to\python.exe` to the setup script if Python 3.12 is not
discovered. After setup, double-click [Start-Wavepacket.cmd](Start-Wavepacket.cmd) to launch
the lab. It opens at [127.0.0.1:8765](http://127.0.0.1:8765); stop the server
with Ctrl+C in its terminal.

For a portable Linux source installation, use an existing Python 3.12 and Node 24:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-build-isolation -e '.[dev,notebooks]'
npm --prefix frontend ci
python scripts/build_frontend.py
wavepacket doctor
wavepacket serve --open-browser
```

A built wheel includes browser assets. Node is needed to build from source,
not to use a correctly built wheel. Source checkouts must build the frontend
before serving the interface.

### WSL2

[Setup-Linux.cmd](Setup-Linux.cmd) enables WSL and virtualisation features
without restarting Windows. The warning “Restart is suppressed because
NoRestart is specified” is expected. Check the generated
`results/setup/wsl-status.json`: if `restart_required` is true, restart Windows
when ready and run the launcher again. This checkpoint does not establish that
Linux tests passed.

Launch `wsl -d Ubuntu-24.04`, create a normal Linux user, then run from Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_wsl.ps1
```

The bootstrap clones committed source into `~/src/wavepacket-lab`; commit the
reviewed Windows changes before using it. It preserves an existing modified
Linux checkout. System packages install as root; the project environment uses
the normal user. Node 24 comes from the official release site and is verified
against its published SHA256. Keep Windows and Linux virtual environments,
`node_modules` and runtime outputs separate. From the Linux checkout, use
`.venv/bin/python` for checks and `.venv/bin/wavepacket serve --port 8766` to
run alongside the Windows lab on port 8765.

## Run experiments and generate evidence

After activating the environment, run:

```bash
wavepacket experiment
wavepacket experiment --name 1d-free
wavepacket experiment --name 2d-double-slit --config-only
wavepacket run examples/2d-rotated.json --estimate-only
wavepacket run examples/2d-rotated.json
wavepacket validate --suite quick --output results/validation/quick
wavepacket validate --suite full --output results/validation/full
wavepacket benchmark --output results/benchmarks
python scripts/run_studies.py accuracy-cost
python scripts/run_studies.py tunnelling
```

Generated runs, validation reports, study results and executed notebook copies
are local outputs, not supplied scientific evidence. Read each generated
`validation.json` for actual status, criteria, configurations and scope. The
quick suite checks basic analytical propagation and implementation properties;
the full suite adds independent Hamiltonian references, time/grid/domain studies,
oscillator physics, absorber calibration and scattering/geometry checks. Passing
fixed cases does not certify arbitrary edited configurations.

The studies freeze a canonical protocol and its SHA256 before execution and
record engine hashes. The launcher fixes numerical threads before importing
NumPy/SciPy. Accuracy/cost compares integrators on the same fixed 1D FD2
Hamiltonian and separately tests a 2D continuum oscillator reference. It reports
raw complex L2 and phase-aligned errors, first-call cost, five interleaved warm
repetitions, median/IQR and unattained targets. Tunnelling compares finite-bandwidth
stationary transmission with finite-time propagation, retained population and
separate time/grid/domain refinements. Timings describe the machine measured.
Use `--output PATH` for a new study directory when the protocol changes.

The default data root is the startup working directory. `wavepacket serve
--data-dir PATH` and the run commands' `--data-dir` select another root;
`--evidence-dir PATH` on `serve` or `validate` selects the validation root.
Validation uses `quick/` and `full/` beneath that root. The browser review tab
reads saved evidence and checks source/configuration fingerprints.

A completed run directory under `runs/` contains resolved `config.json`, lifecycle
`record.json`, provenance and artifact hashes in `manifest.json`, complex128
snapshots in `state.h5`, diagnostics at their configured cadence in
`observables.csv`, `summary.json` and a self-contained `report.html`. One worker
owns a run; cancellation or failure retains its explicit status. Conditional
observables can be null with a reason
when surviving mass is unresolved. Raw norm and absorption accounting remain
available. Regenerate a saved report with `wavepacket report PATH_TO_RUN`.

## Numerical model and limits

The dimensionless core solves

$$
i\partial_t\psi=\left[-\frac12\nabla^2+V-iW\right]\psi,
\qquad P=\Delta\Omega\sum_j|\psi_j|^2.
$$

Here `W >= 0` is the optional complex absorbing potential (CAP), and
`DeltaOmega` is the grid-cell volume. Initial states are normalised once;
propagators never renormalise away drift or absorption. Grids exclude the upper
endpoint and are periodic. Coordinates use `(x, y)`; 2D arrays use `(ny, nx)`.

Fourier kinetic energy has symbol `k^2/2`; periodic second-order finite
differences (FD2) use `(1 - cos(k*dx))/dx^2`, summed over axes. For `W = 0`,
Strang splitting uses `S2(h) = exp(-ihV/2) exp(-ihT) exp(-ihV/2)` and has
second-order global time accuracy on a fixed discrete Hamiltonian. Crank–Nicolson solves
`(I + ihH/2) psi_next = (I - ihH/2) psi` and is restricted to closed 1D FD2
systems. Fourth-order Yoshida uses `S2(w1*h) S2(w0*h) S2(w1*h)`, where
`w1 = 1/(2 - 2^(1/3))` and `w0 = -2^(1/3)/(2 - 2^(1/3))`. Its negative
intermediate step amplifies damping, so CAP requires positive-step Strang.

Electron display units use a chosen length `L0` in nm:

$$
E_0=\frac{\hbar^2}{m_eL_0^2},\qquad
t_0=\frac{\hbar}{E_0},\qquad p_0=\frac{\hbar}{L_0}.
$$

The kinetic factor one-half stays in the operator. At `L0 = 1 nm`,
`E0 ≈ 0.0761996 eV` and `t0 ≈ 8.63799 fs`. Configuration and stored states
remain dimensionless; display conversion does not alter the trajectory.
Gaussian `sigma` denotes the standard deviation of probability density, with
momentum standard deviation `1/(2*sigma)` for an unchirped packet.

Norm conservation and a plausible animation do not establish physical accuracy.
Temporal, spatial, domain, boundary and reference errors need separate checks.
Compare time integrators on the same discrete Hamiltonian; FD2 and spectral
kinetic operators represent different finite problems. Abrupt barriers and
finite slit walls need geometry/grid refinement. CAP approximates an open
boundary and intentionally removes probability; calibrated cases do not prove
reflection-free performance for every packet. Long resonant dwell times can
leave substantial population between barriers, so early transmitted probability
need not equal asymptotic stationary transmission.

Screen current is signed and integrated at every numerical step. Negative flux
and repeated crossings are retained; it is not a first-detection model. This
release does not include spin, interacting particles, collapse, nonlinear or
driven evolution, exact infinite boundaries or checkpoint resumption.

## Development and verification

Use the project interpreter: `.venv\Scripts\python.exe` on Windows or
`.venv/bin/python` on Linux. After activating it:

```bash
python -m pytest --basetemp=.pytest-work
python -m ruff check src tests scripts
python -m mypy src/wavepacket
npm --prefix frontend run check:api
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test
python scripts/build_frontend.py
python scripts/check_browser.py
python scripts/execute_notebooks.py
python scripts/profile_performance.py
python -m build --no-isolation
```

`check_browser.py` starts its own temporary API process and data directory. The
browser harness uses installed Chrome on Windows and Playwright Chromium on
Linux. Install Chromium with `npm --prefix frontend exec -- playwright install
chromium` if needed, and set `WAVEPACKET_BROWSER=chromium` on Windows to use it.
To test a server already running, use `npm --prefix frontend run test:browser`;
`WAVEPACKET_URL` overrides its URL. Browser screenshots/logs stay under ignored
`frontend/tests/artifacts/`. These checks need loopback sockets and process/IPC
access; run them in a normal terminal if a sandbox blocks those facilities.

The four source notebooks in [notebooks/](notebooks/) cover methods, independent
validation, scattering/boundaries and measured work–precision comparisons. They
import the shared engine. Execution writes copies and a summary under
`results/notebook_runs/`; `--in-place` explicitly refreshes source notebooks.

After generating full validation and both canonical studies above, run
`python scripts/verify_release.py --browser`. It checks saved evidence against
current sources/protocols, executes current notebooks, rebuilds browser assets
and packages, inspects wheel/source archive contents and checks a fresh wheel
installation. Use a disposable checkout if existing research outputs must stay
untouched. The bounded CI in [.github/workflows/ci.yml](.github/workflows/ci.yml)
checks selected numerical regressions and frontend build contracts on Linux.
It does not execute the full research, browser, WSL or release protocol.
Report the actual platform and results of each invocation.

For frontend development, start the API on port 8765 and run
`npm --prefix frontend run dev`; Vite proxies `/api`. The Python backend owns
scientific input validation. `npm --prefix frontend run generate:api` regenerates
the TypeScript contract from OpenAPI; `check:api` detects drift. Set
`WAVEPACKET_PYTHON` to select its Python executable. The local server exposes
OpenAPI at `/openapi.json` and interactive API documentation at `/docs`.

## Source map and attribution

| Path | Purpose |
|---|---|
| [src/wavepacket/](src/wavepacket/) | Models, operators, propagators, observables, storage, CLI/API, validation and studies |
| [frontend/](frontend/) | React/TypeScript interface, generated API contract and browser tests |
| [tests/](tests/) | Numerical, scientific, API, persistence, resource and packaging checks |
| [notebooks/](notebooks/) | Four executable research notebooks |
| [examples/](examples/) | Runnable experiment configurations |
| [scripts/](scripts/) | Setup, frontend build, studies, notebooks, profiling and release verification |

The interface bundles [Host Grotesk](https://github.com/Element-Type/HostGrotesk)
(400/500/600) and [Atkinson Hyperlegible Mono](https://github.com/googlefonts/atkinson-hyperlegible-next-mono)
(400/500). The TTFs were supplied by the Google Fonts CSS API on 2026-10-29;
their accompanying [Host Grotesk licence](frontend/public/fonts/HostGrotesk-OFL.txt)
and [Atkinson licence](frontend/public/fonts/AtkinsonHyperlegibleMono-OFL.txt)
come from the corresponding `google/fonts` families. Both use the SIL Open Font
License 1.1; retain these licences when redistributing the fonts. Fonts are
served locally, without a runtime font-service dependency.

The 1 × 256 PNG keys in [frontend/public/scales/](frontend/public/scales/) are
sampled from this project's [field-renderer RGB formulas](frontend/src/plots.tsx),
with maximum at the top: density uses all five stops, phase runs from `+pi` to
`-pi`, and signed current from `+1` to `-1`. Regenerate the keys with the same
8-bit rounding if those mappings change; renderer masking and potential
overlays remain separate.

Scientific implementation references include [SciPy's matrix-exponential action](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.expm_multiply.html),
[SciPy physical constants](https://docs.scipy.org/doc/scipy/reference/constants.html)
and [Yoshida's symmetric composition](https://tlakoba.w3.uvm.edu/math6737/for_final_topics/SSM_1990_Yoshida.pdf).
The project implements established methods; claims concern their measured
implementation and validation. Original project code is licensed for
non-commercial use under [PolyForm Noncommercial 1.0.0](LICENSE).
