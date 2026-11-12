import {
  Activity,
  ArrowDownToLine,
  ArrowLeftRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileJson,
  FlaskConical,
  Layers3,
  Moon,
  Pause,
  Play,
  RotateCcw,
  Search,
  Settings2,
  SkipBack,
  SkipForward,
  Square,
  Sun,
  Terminal,
  Waves,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import ConfigPanel from './ConfigPanel';
import { DiagnosticPlot, FieldView, LinePlot, SlicePlot } from './plots';
import Review from './Review';
import type { Config, Frame, Preset, Row, Run, ViewMode } from './types';
import { ApiError, activeRun, api, CORE_UNITS, displayName } from './types';
import { useCanonicalDraft, useCanonicalUnits } from './useCanonicalDraft';

type Tab = 'field' | 'diagnostics' | 'compare' | 'review';
const format = (n: number | null | undefined, digits = 5) =>
  n == null || !Number.isFinite(n)
    ? 'Unavailable'
    : Math.abs(n) < 0.0001 && n !== 0
      ? n.toExponential(3)
      : Number(n.toPrecision(digits)).toString();
const multiply = (value: number | null | undefined, factor: number) =>
  value == null ? null : value * factor;
const difference = (latest: number | null, initial: number | null) =>
  latest === null || initial === null ? null : latest - initial;

function downloadConfig(config: Config) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' }),
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = `${config.name.replaceAll(/[^a-zA-Z0-9_-]/g, '_')}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function Status({ run }: { run: Run | null }) {
  return (
    <span className={`run-status ${run?.status ?? 'ready'}`}>
      {run ? displayName(run.status) : 'Ready to propagate'}
    </span>
  );
}

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem('wavepacket-theme') ?? 'dark');
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<Preset | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [original, setOriginal] = useState('');
  const [history, setHistory] = useState<Run[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [runSelection, setRunSelection] = useState<{ id: string } | null>(null);
  const runId = runSelection?.id ?? null;
  const [frame, setFrame] = useState<Frame | null>(null);
  const [frames, setFrames] = useState<{ index: number; time: number }[]>([]);
  const [frameIndex, setFrameIndex] = useState(0);
  const [rows, setRows] = useState<Row[]>([]);
  const [comparison, setComparison] = useState<Run | null>(null);
  const [comparisonRows, setComparisonRows] = useState<Row[]>([]);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const comparisonRequest = useRef({ id: 0, controller: null as AbortController | null });
  const contextVersion = useRef(0);
  const importRequest = useRef(0);
  const [tab, setTab] = useState<Tab>('field');
  const [view, setView] = useState<ViewMode>('density');
  const [showPotential, setShowPotential] = useState(true);
  const [autoscale, setAutoscale] = useState(false);
  const [displayUnitMode, setDisplayUnitMode] = useState<Config['units']['mode']>('dimensionless');
  const [slice, setSlice] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [diagnostic, setDiagnostic] = useState('norm');
  const [error, setError] = useState('');
  const [runError, setRunError] = useState<{ message: string; dismissed: boolean } | null>(null);
  const [starting, setStarting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [showParameters, setShowParameters] = useState(true);
  const [exportOpen, setExportOpen] = useState(false);
  const imported = useRef<HTMLInputElement>(null);
  const sourceConfig = run?.config ?? config;
  const resultUnits = useCanonicalUnits(sourceConfig?.units.length_nm ?? null);
  const draftUnits = useCanonicalUnits(config?.units.length_nm ?? null);
  const comparisonUnits = useCanonicalUnits(comparison?.config.units.length_nm ?? null);
  const canonicalDraft = useCanonicalDraft(config);
  const units = resultUnits.units ?? CORE_UNITS;
  const physical = displayUnitMode === 'electron' && resultUnits.units !== null;
  const running = activeRun(run);
  const errors = [...canonicalDraft.errors, ...(draftUnits.error ? [draftUnits.error] : [])];
  const checking = canonicalDraft.checking || draftUnits.checking;
  const modified = config ? JSON.stringify(config) !== original : false;

  const clearComparison = useCallback(() => {
    contextVersion.current += 1;
    comparisonRequest.current.controller?.abort();
    comparisonRequest.current.id += 1;
    setComparison(null);
    setComparisonRows([]);
    setComparisonLoading(false);
  }, []);
  useEffect(
    () => () => {
      contextVersion.current += 1;
      comparisonRequest.current.controller?.abort();
    },
    [],
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('wavepacket-theme', theme);
  }, [theme]);
  const refreshHistory = useCallback(async () => {
    try {
      setHistory(await api<Run[]>('/runs'));
    } catch {
      /* connection errors are reported by the main request */
    }
  }, []);
  useEffect(() => {
    let cancelled = false;
    api<Preset[]>('/presets')
      .then((items) => {
        if (cancelled) return;
        setConnected(true);
        setPresets(items);
        if (items.length) {
          setPreset(items[0]);
          setConfig(structuredClone(items[0].config));
          setOriginal(JSON.stringify(items[0].config));
          setDisplayUnitMode(items[0].config.units.mode);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(`Could not reach the local engine. ${e.message}`);
      });
    void refreshHistory();
    return () => {
      cancelled = true;
    };
  }, [refreshHistory]);

  useEffect(() => {
    setRunError(null);
    if (!runSelection) return;
    const { id: runId } = runSelection;
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const state = await api<Run>(`/runs/${runId}`);
        if (stopped) return;
        setRun(state);
        setRunError(null);
        setConnected(true);
        if (activeRun(state)) {
          try {
            const preview = await api<Frame>(`/runs/${runId}/preview`);
            if (!stopped && (!preview.run_id || preview.run_id === runId)) {
              setFrame(preview);
              setRows((old) =>
                [
                  ...old.filter((r) => (r.time ?? r.t ?? 0) < preview.time),
                  { time: preview.time, ...preview.observables },
                ].slice(-2000),
              );
            }
          } catch {
            /* the first frame may not exist yet */
          }
          if (!stopped) timer = setTimeout(poll, 500);
        } else {
          const results = await Promise.allSettled([
            api<{ index: number; time: number }[]>(`/runs/${runId}/frames`),
            api<Row[]>(`/runs/${runId}/observables`),
          ]);
          if (stopped) return;
          if (results[0].status === 'fulfilled') {
            const values = results[0].value;
            setFrames(values);
            setFrameIndex(Math.max(0, values.length - 1));
          }
          if (results[1].status === 'fulfilled') setRows(results[1].value);
          const failures = results.flatMap((result, index) =>
            result.status === 'rejected'
              ? [
                  `Saved ${index === 0 ? 'frames' : 'observables'} unavailable: ${result.reason.message}`,
                ]
              : [],
          );
          if (failures.length)
            setRunError({ message: `Run ${runId}: ${failures.join(' ')}`, dismissed: false });
          void refreshHistory();
        }
      } catch (e) {
        if (!stopped) {
          setRunError({
            message: `Run ${runId} status unavailable: ${(e as Error).message}`,
            dismissed: false,
          });
          setConnected(false);
          if (
            e instanceof TypeError ||
            (e instanceof ApiError && (e.status >= 500 || e.status === 408 || e.status === 429))
          )
            timer = setTimeout(poll, 1000);
        }
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runSelection, refreshHistory]);

  useEffect(() => {
    if (!runId || !frames.length || running) return;
    let stopped = false;
    api<Frame>(`/runs/${runId}/frames/${frames[frameIndex]?.index ?? frameIndex}`)
      .then((f) => {
        if (!stopped && (!f.run_id || f.run_id === runId)) setFrame(f);
      })
      .catch((e) => {
        if (!stopped) setError(e.message);
      });
    return () => {
      stopped = true;
    };
  }, [runId, frames, frameIndex, running]);
  useEffect(() => {
    if (!playing || frames.length < 2) return;
    const timer = setInterval(
      () =>
        setFrameIndex((i) => {
          if (i >= frames.length - 1) {
            setPlaying(false);
            return i;
          }
          return i + 1;
        }),
      180 / speed,
    );
    return () => clearInterval(timer);
  }, [playing, frames.length, speed]);

  const selectPreset = (item: Preset) => {
    if (running || starting) return;
    clearComparison();
    setDisplayUnitMode(item.config.units.mode);
    setPreset(item);
    setConfig(structuredClone(item.config));
    setOriginal(JSON.stringify(item.config));
    setRunSelection(null);
    setRun(null);
    setFrame(null);
    setRows([]);
    setFrames([]);
    setPlaying(false);
    setError('');
    setSlice(-1);
  };
  const start = async () => {
    if (!canonicalDraft.resolved || checking || errors.length || running || starting) return;
    clearComparison();
    setStarting(true);
    setError('');
    setPlaying(false);
    try {
      const result = await api<Run>('/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(canonicalDraft.resolved),
      });
      setDisplayUnitMode(result.config.units.mode);
      setFrames([]);
      setRows([]);
      setFrame(null);
      setSlice(-1);
      setRun(result);
      setRunSelection({ id: result.id });
      await refreshHistory();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };
  const cancel = async () => {
    if (runId) {
      try {
        setRun(await api<Run>(`/runs/${runId}/cancel`, { method: 'POST' }));
      } catch (e) {
        setError((e as Error).message);
      }
    }
  };
  const loadHistory = (item: Run) => {
    if (starting || (running && runId !== item.id)) return;
    if (runId === item.id) {
      if (runError) setRunSelection({ id: item.id });
      return;
    }
    clearComparison();
    setDisplayUnitMode(item.config.units.mode);
    setRunSelection({ id: item.id });
    setRun(item);
    setConfig(structuredClone(item.config));
    setOriginal(JSON.stringify(item.config));
    setFrame(null);
    setFrames([]);
    setRows([]);
    setPlaying(false);
    setPreset(presets.find((p) => p.config.name === item.config.name) ?? null);
    setError('');
    setSlice(-1);
  };
  const chooseComparison = async (id: string) => {
    comparisonRequest.current.controller?.abort();
    const controller = new AbortController();
    const requestId = ++comparisonRequest.current.id;
    comparisonRequest.current.controller = controller;
    const context = contextVersion.current;
    const item = history.find((r) => r.id === id) ?? null;
    setComparison(item);
    setComparisonRows([]);
    setComparisonLoading(!!item);
    if (!item) return;
    const current = () =>
      comparisonRequest.current.id === requestId &&
      contextVersion.current === context &&
      !controller.signal.aborted;
    try {
      const values = await api<Row[]>(`/runs/${id}/observables`, { signal: controller.signal });
      if (current()) setComparisonRows(values);
    } catch (e) {
      if (current()) setError((e as Error).message);
    } finally {
      if (current()) setComparisonLoading(false);
    }
  };
  const importConfig = async (file: File) => {
    const requestId = ++importRequest.current;
    const context = contextVersion.current;
    try {
      const parsed: unknown = JSON.parse(await file.text());
      const resolved = await api<Config>('/config/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      });
      if (requestId !== importRequest.current || context !== contextVersion.current) return;
      clearComparison();
      setConfig(resolved);
      setOriginal(JSON.stringify(resolved));
      setDisplayUnitMode(resolved.units.mode);
      setPreset(null);
      setRun(null);
      setRunSelection(null);
      setFrames([]);
      setFrame(null);
      setRows([]);
      setPlaying(false);
      setSlice(-1);
      setError('');
    } catch (e) {
      if (requestId === importRequest.current && context === contextVersion.current)
        setError(`Configuration import failed: ${(e as Error).message}`);
    }
  };
  const evidence = preset?.evidence ?? 'Custom configuration';
  const visible = presets.filter(
    (p) =>
      (filter === 'all' || p.dimension === Number(filter)) &&
      `${p.name} ${p.question}`.toLowerCase().includes(search.toLowerCase()),
  );
  const obs = frame?.observables ?? rows[rows.length - 1] ?? {};
  const diagnostics = rows.length
    ? Object.keys(rows[0]).filter((k) => k !== 'time' && k !== 't')
    : ['norm', 'energy', 'x_mean', 'edge_probability'];
  const selectedDiag = diagnostics.includes(diagnostic) ? diagnostic : diagnostics[0];
  const artifact = (name: string) =>
    `/api/runs/${encodeURIComponent(runId ?? '')}/artifacts/${encodeURIComponent(name)}`;

  return (
    <div className="application">
      <header className="app-header">
        <a href="/" className="brand" aria-label="Wavepacket home">
          <span className="brand-symbol">
            <Waves size={26} />
          </span>
          <strong>Wavepacket</strong>
        </a>
        <div className="header-divider" />
        <span className="header-caption">Quantum dynamics laboratory</span>
        <div className="header-right">
          <span className={`connection ${connected ? 'online' : ''}`}>
            {connected ? 'Local engine' : 'Connecting'}
          </span>
          <span className="cpu-label">CPU, complex128</span>
          <button
            type="button"
            className="icon-button"
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>
      <div className={`lab-layout ${showParameters ? '' : 'parameters-hidden'}`}>
        <aside className="library-panel" aria-label="Experiment library">
          <div className="library-heading">
            <FlaskConical size={17} />
            <h2>Experiments</h2>
            <span>{presets.length}</span>
          </div>
          <div className="search-field">
            <Search size={14} />
            <input
              aria-label="Search experiments"
              placeholder="Find an experiment…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <fieldset className="dimension-filter" aria-label="Filter by dimension">
            {[
              ['all', 'All'],
              ['1', '1D'],
              ['2', '2D'],
            ].map(([value, label]) => (
              <button
                type="button"
                key={value}
                aria-pressed={filter === value}
                className={filter === value ? 'selected' : ''}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </fieldset>
          <nav className="experiment-list" aria-label="Choose experiment">
            {visible.map((p, i) => (
              <button
                type="button"
                key={p.id}
                disabled={running || starting}
                className={`experiment-item ${preset?.id === p.id ? 'selected' : ''}`}
                onClick={() => selectPreset(p)}
              >
                <span className="experiment-index">
                  {String(presets.indexOf(p) + 1 || i + 1).padStart(2, '0')}
                </span>
                <span>
                  <strong>{p.name}</strong>
                  <small>
                    {p.dimension}D, {displayName(p.config.potential.kind)}
                  </small>
                </span>
              </button>
            ))}
            {!visible.length && (
              <p className="library-empty">
                {presets.length
                  ? 'No matching experiments.'
                  : 'Loading the local experiment catalogue…'}
              </p>
            )}
          </nav>
          <div className="history-heading">
            <Clock3 size={14} />
            <h3>Recent runs</h3>
            <button
              type="button"
              className="icon-button small"
              aria-label="Refresh run history"
              onClick={() => void refreshHistory()}
            >
              <RotateCcw size={13} />
            </button>
          </div>
          <div className="history-list">
            {history.slice(0, 7).map((item) => (
              <button
                type="button"
                key={item.id}
                disabled={starting || (running && item.id !== runId)}
                className={item.id === runId ? 'selected' : ''}
                onClick={() => loadHistory(item)}
              >
                <span>
                  <strong>{item.config.name}</strong>
                  <small>
                    {item.id.slice(0, 8)}, {displayName(item.status)}
                  </small>
                </span>
              </button>
            ))}
            {!history.length && <p className="library-empty">Completed runs will appear here.</p>}
          </div>
          <div className="library-footer">
            <Terminal size={14} />
            <span>
              Local simulations.
              <br />
              No account required.
            </span>
          </div>
        </aside>

        <main className="workspace">
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button type="button" aria-label="Dismiss error" onClick={() => setError('')}>
                <X size={15} />
              </button>
            </div>
          )}
          {runError && !runError.dismissed && (
            <div className="error-banner" role="alert">
              <span>{runError.message} Select this run again to retry.</span>
              <button
                type="button"
                aria-label="Dismiss run error"
                onClick={() => setRunError((error) => error && { ...error, dismissed: true })}
              >
                <X size={15} />
              </button>
            </div>
          )}
          <div className="workspace-heading">
            <div>
              <h1>{preset?.name ?? config?.name ?? 'Wavepacket'}</h1>
              <p>
                {preset?.question ?? 'Inspect the model, propagate the state, and test the result.'}
              </p>
            </div>
            <button
              type="button"
              className={`icon-button parameter-toggle ${showParameters ? 'active' : ''}`}
              aria-label="Toggle parameter panel"
              aria-pressed={showParameters}
              onClick={() => setShowParameters(!showParameters)}
            >
              <Settings2 size={18} />
            </button>
          </div>
          <div className="experiment-meta">
            <span className="experiment-context">
              {config?.grid.points.length ?? '—'}D experiment, {preset?.id ?? 'Custom'}
            </span>
            <span className="evidence-label">
              <BookOpen size={12} />
              {evidence}
            </span>
            {modified && (
              <span className="modified-label">Edited configuration, revalidation required</span>
            )}
            <Status run={run} />
          </div>

          <div className="workspace-tabs" role="tablist" aria-label="Laboratory views">
            {(
              [
                ['field', Waves, 'Wavefunction'],
                ['diagnostics', Activity, 'Diagnostics'],
                ['compare', ArrowLeftRight, 'Compare'],
                ['review', BookOpen, 'Review & theory'],
              ] as const
            ).map(([value, Icon, label]) => (
              <button
                type="button"
                key={value}
                role="tab"
                id={`tab-${value}`}
                aria-controls={`panel-${value}`}
                tabIndex={tab === value ? 0 : -1}
                aria-selected={tab === value}
                className={tab === value ? 'selected' : ''}
                onClick={() => setTab(value)}
                onKeyDown={(e) => {
                  const order: Tab[] = ['field', 'diagnostics', 'compare', 'review'];
                  const next =
                    e.key === 'Home'
                      ? order[0]
                      : e.key === 'End'
                        ? order[3]
                        : e.key === 'ArrowRight'
                          ? order[(order.indexOf(value) + 1) % 4]
                          : e.key === 'ArrowLeft'
                            ? order[(order.indexOf(value) + 3) % 4]
                            : null;
                  if (next) {
                    e.preventDefault();
                    setTab(next);
                    document.getElementById(`tab-${next}`)?.focus();
                  }
                }}
              >
                <Icon size={15} />
                {label}
              </button>
            ))}
          </div>

          {tab === 'field' && (
            <section
              id="panel-field"
              role="tabpanel"
              aria-labelledby="tab-field"
              className="field-workspace"
              aria-label="Wavefunction visualization"
            >
              <div className="plot-toolbar">
                <fieldset className="segmented-control" aria-label="Displayed field">
                  {(['density', 'phase', 'current'] as const).map((v) => (
                    <button
                      type="button"
                      key={v}
                      aria-pressed={view === v}
                      className={view === v ? 'selected' : ''}
                      onClick={() => setView(v)}
                    >
                      {v === 'density'
                        ? '|ψ|² Density'
                        : v === 'phase'
                          ? 'arg ψ Phase'
                          : 'jₓ Current'}
                    </button>
                  ))}
                </fieldset>
                <label className="inline-check">
                  <input
                    type="checkbox"
                    checked={showPotential}
                    onChange={(e) => setShowPotential(e.target.checked)}
                  />
                  Potential overlay
                </label>
                <label className="inline-check">
                  <input
                    type="checkbox"
                    checked={autoscale}
                    onChange={(e) => setAutoscale(e.target.checked)}
                  />
                  Autoscale each frame
                </label>
                <label className="inline-check">
                  Result units
                  <select
                    aria-label="Result display units"
                    value={displayUnitMode}
                    onChange={(e) => setDisplayUnitMode(e.target.value as Config['units']['mode'])}
                  >
                    <option value="dimensionless">Dimensionless</option>
                    <option value="electron">nm / fs / eV</option>
                  </select>
                </label>
              </div>
              {displayUnitMode === 'electron' && !resultUnits.units && (
                <p className="field-note" role="status">
                  {resultUnits.error
                    ? `Physical units unavailable: ${resultUnits.error}`
                    : 'Loading physical conversion metadata…'}{' '}
                  Displaying dimensionless core values.
                </p>
              )}
              <div className={`field-stage ${!frame ? 'empty-stage' : ''}`}>
                {frame ? (
                  <FieldView
                    frame={frame}
                    mode={view}
                    potential={showPotential}
                    physical={!!physical}
                    units={units}
                    slice={slice}
                    autoscale={autoscale}
                    currentOffset={
                      sourceConfig?.solver.kinetic === 'fd2'
                        ? (sourceConfig.grid.bounds[0][1] - sourceConfig.grid.bounds[0][0]) /
                          sourceConfig.grid.points[0] /
                          2
                        : 0
                    }
                  />
                ) : (
                  <div className="empty-field">
                    <div className="empty-wave">
                      <Waves size={43} />
                    </div>
                    <h2>{running ? 'Preparing the initial state…' : 'The experiment is ready.'}</h2>
                    <p>
                      {running
                        ? 'The numerical worker will publish its first frame shortly.'
                        : 'Review the parameters, then propagate the wavefunction.'}
                    </p>
                    <span>
                      {config?.solver.method === 'cn'
                        ? 'Crank–Nicolson'
                        : config?.solver.method === 'yoshida4'
                          ? 'Yoshida fourth order'
                          : 'Strang split operator'}
                      {', '}
                      {config?.grid.points.join(' × ')} grid
                    </span>
                  </div>
                )}
              </div>
              <div className="plot-caption">
                <span>
                  {frame
                    ? `t = ${format(frame.time * (physical ? units.time_fs : 1))} ${physical ? 'fs' : '(dimensionless)'}`
                    : 'No numerical frames yet'}
                </span>
                <span>
                  {view === 'phase'
                    ? 'Phase visibility is suppressed where density is negligible.'
                    : view === 'current' && sourceConfig?.solver.kinetic === 'fd2'
                      ? 'FD2 link current is located on positive half-grid faces.'
                      : showPotential && config?.grid.points.length === 1
                        ? 'Potential is rescaled for overlay; inspect energy in diagnostics.'
                        : frame?.dimension === 2
                          ? 'x increases right; y increases upward.'
                          : 'Initial normalisation only; no forced norm correction.'}
                </span>
              </div>
              {frames.length > 1 && (
                <div className="playback">
                  <fieldset className="playback-transport" aria-label="Saved frame transport">
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="First saved frame"
                      disabled={frameIndex === 0}
                      onClick={() => {
                        setPlaying(false);
                        setFrameIndex(0);
                      }}
                    >
                      <SkipBack size={16} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Previous saved frame"
                      disabled={frameIndex === 0}
                      onClick={() => {
                        setPlaying(false);
                        setFrameIndex((i) => Math.max(0, i - 1));
                      }}
                    >
                      <ChevronLeft size={17} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={playing ? 'Pause replay' : 'Play replay'}
                      onClick={() => {
                        if (frameIndex === frames.length - 1) setFrameIndex(0);
                        setPlaying(!playing);
                      }}
                    >
                      {playing ? <Pause size={17} /> : <Play size={17} />}
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Next saved frame"
                      disabled={frameIndex === frames.length - 1}
                      onClick={() => {
                        setPlaying(false);
                        setFrameIndex((i) => Math.min(frames.length - 1, i + 1));
                      }}
                    >
                      <ChevronRight size={17} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Last saved frame"
                      disabled={frameIndex === frames.length - 1}
                      onClick={() => {
                        setPlaying(false);
                        setFrameIndex(frames.length - 1);
                      }}
                    >
                      <SkipForward size={16} aria-hidden="true" />
                    </button>
                  </fieldset>
                  <input
                    aria-label="Saved frame"
                    type="range"
                    min={0}
                    max={frames.length - 1}
                    value={frameIndex}
                    onChange={(e) => {
                      setPlaying(false);
                      setFrameIndex(Number(e.target.value));
                    }}
                  />
                  <span className="playback-position">
                    {frameIndex + 1} / {frames.length}
                  </span>
                  <select
                    aria-label="Replay speed"
                    value={speed}
                    onChange={(e) => setSpeed(Number(e.target.value))}
                  >
                    <option value={0.5}>0.5×</option>
                    <option value={1}>1×</option>
                    <option value={2}>2×</option>
                    <option value={4}>4×</option>
                  </select>
                </div>
              )}
              {frame?.dimension === 2 && (
                <div className="slice-section">
                  <div className="section-line">
                    <h3>Horizontal density slice</h3>
                    <label>
                      <input
                        type="checkbox"
                        checked={slice >= 0}
                        onChange={(e) =>
                          setSlice(
                            e.target.checked ? Math.floor((frame.axes.y?.length ?? 1) / 2) : -1,
                          )
                        }
                      />
                      Show slice
                    </label>
                  </div>
                  {slice >= 0 && (
                    <>
                      <input
                        aria-label="Slice y index"
                        className="slice-slider"
                        type="range"
                        min={0}
                        max={(frame.axes.y?.length ?? 1) - 1}
                        value={slice}
                        onChange={(e) => setSlice(Number(e.target.value))}
                      />
                      <SlicePlot
                        frame={frame}
                        index={slice}
                        units={units}
                        physical={!!physical}
                        autoscale={autoscale}
                      />
                    </>
                  )}
                </div>
              )}
              {frame?.screen && (
                <section className="screen-section" aria-label="Screen diagnostics">
                  <div className="section-line">
                    <div>
                      <h3>Screen diagnostics</h3>
                      <p>
                        Current plane x ={' '}
                        {format(frame.screen.x * (physical ? units.length_nm : 1))}; density node x
                        ={' '}
                        {format(
                          (frame.screen.density_x ?? frame.screen.x) *
                            (physical ? units.length_nm : 1),
                        )}{' '}
                        {physical ? 'nm' : '(dimensionless)'}. Density and integrated current
                        measure different quantities.
                      </p>
                    </div>
                  </div>
                  <div className="screen-plots">
                    <LinePlot
                      height={200}
                      xLabel={physical ? 'y (nm)' : 'y (dimensionless)'}
                      yLabel={physical ? 'Signed ∫jₓ dt (nm⁻¹)' : 'Signed ∫jₓ dt'}
                      series={[
                        {
                          x: frame.screen.y.map((v) => v * (physical ? units.length_nm : 1)),
                          y: frame.screen.current_integral.map(
                            (v) => v * (physical ? units.momentum_inverse_nm : 1),
                          ),
                          label: 'Signed integrated current',
                        },
                      ]}
                    />
                    <LinePlot
                      height={200}
                      xLabel={physical ? 'y (nm)' : 'y (dimensionless)'}
                      yLabel={physical ? 'Screen density (nm⁻²)' : 'Screen density |ψ|²'}
                      fixedRange={[
                        0,
                        (autoscale ? Math.max(...frame.screen.density) : frame.density_scale_max) *
                          (physical ? units.density_per_nm2 : 1) || 1,
                      ]}
                      series={[
                        {
                          x: frame.screen.y.map((v) => v * (physical ? units.length_nm : 1)),
                          y: frame.screen.density.map(
                            (v) => v * (physical ? units.density_per_nm2 : 1),
                          ),
                          label: 'Instantaneous density',
                          color: 'var(--plot-reference)',
                        },
                      ]}
                    />
                  </div>
                  <p className="field-note">
                    Negative current contributions are retained. Recrossings and finite-grid effects
                    prevent interpreting this profile as a general first-detection distribution.
                  </p>
                </section>
              )}
              <p className="field-note">
                {autoscale
                  ? 'Per-frame autoscale: colour brightness changes with the frame peak.'
                  : frame?.density_scale_scope === 'max_across_saved_frames'
                    ? 'Shared density scale: maximum across saved frames (not a continuous-time maximum).'
                    : 'Shared density scale: running maximum observed so far; finalized replay uses all saved frames.'}
                {run && (
                  <>
                    {' '}
                    Result scale L₀ = {run.config.units.length_nm} nm, fixed by saved run{' '}
                    {run.id.slice(0, 8)}.
                  </>
                )}
              </p>
              {frame?.validity && frame.validity.conditional_status !== 'resolved' && (
                <p className="field-note" role="status">
                  Conditional observables unavailable:{' '}
                  {frame.validity.reason ?? frame.validity.conditional_status}. Norm reporting floor{' '}
                  {format(frame.validity.reporting_floor)} relative to initial norm{' '}
                  {format(frame.validity.initial_norm)}.
                </p>
              )}
              {frame?.validity?.uncertainty_status && (
                <p className="field-note">
                  Uncertainty interpretation: {displayName(frame.validity.uncertainty_status)}.{' '}
                  {frame.validity.uncertainty_reason}
                </p>
              )}
              <div className="metric-strip">
                <div>
                  <span>Surviving probability</span>
                  <strong>{format(obs.norm, 8)}</strong>
                  <small>
                    {sourceConfig?.boundary.kind === 'cap'
                      ? 'CAP intentionally removes norm'
                      : 'Closed-system norm'}
                  </small>
                </div>
                <div>
                  <span>Mean energy</span>
                  <strong>
                    {format(multiply(obs.energy, physical ? units.energy_ev : 1))}
                    <em>{physical ? ' eV' : ' (dimensionless)'}</em>
                  </strong>
                  <small>
                    {sourceConfig?.boundary.kind === 'cap'
                      ? 'Conditional on surviving state'
                      : 'Static Hamiltonian expectation'}
                  </small>
                </div>
                <div>
                  <span>Position ⟨x⟩</span>
                  <strong>
                    {format(multiply(obs.x_mean, physical ? units.length_nm : 1))}
                    <em>{physical ? ' nm' : ''}</em>
                  </strong>
                  <small>Grid-weighted expectation</small>
                </div>
                <div>
                  <span>Boundary-edge probability</span>
                  <strong>{format(obs.edge_probability)}</strong>
                  <small>Diagnostic, not an accuracy proof</small>
                </div>
              </div>
              <div className="scientific-note">
                <CircleHelp size={15} />
                <p>
                  {sourceConfig?.boundary.kind === 'cap'
                    ? 'Absorbing boundaries approximate an open domain. Check absorber reflection and probability-loss accounting separately.'
                    : 'Norm conservation alone does not establish accurate dynamics. Use independent references and timestep, grid, and domain refinement.'}
                </p>
              </div>
            </section>
          )}

          {tab === 'diagnostics' && (
            <section
              id="panel-diagnostics"
              role="tabpanel"
              aria-labelledby="tab-diagnostics"
              className="diagnostics-content"
            >
              <div className="section-line">
                <div>
                  <h2>Measurements over time</h2>
                  <p>Values come from the scientific grid, independently of preview resolution.</p>
                </div>
                <select
                  aria-label="Diagnostic observable"
                  value={selectedDiag}
                  onChange={(e) => setDiagnostic(e.target.value)}
                >
                  {diagnostics.map((key) => (
                    <option value={key} key={key}>
                      {displayName(key)}
                    </option>
                  ))}
                </select>
              </div>
              {rows.length ? (
                <>
                  <DiagnosticPlot
                    rows={rows}
                    physical={!!physical}
                    units={units}
                    selected={selectedDiag}
                  />
                  <div className="observable-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Observable</th>
                          <th>Initial</th>
                          <th>Latest</th>
                          <th>Change</th>
                        </tr>
                      </thead>
                      <tbody>
                        {diagnostics.map((key) => (
                          <tr key={key}>
                            <td>{displayName(key)}</td>
                            <td>{format(rows[0][key], 8)}</td>
                            <td>{format(rows[rows.length - 1][key], 8)}</td>
                            <td>
                              {format(difference(rows[rows.length - 1][key], rows[0][key]), 5)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="field-note">
                    The numerical table uses dimensionless core values. The time axis follows your
                    display unit selection. CAP energy and moments are conditional on the surviving
                    state.
                  </p>
                </>
              ) : (
                <div className="tab-empty">
                  <Activity size={32} />
                  <h3>No measurements yet</h3>
                  <p>Run an experiment to inspect its observables and drift.</p>
                </div>
              )}
            </section>
          )}

          {tab === 'compare' && (
            <section
              id="panel-compare"
              role="tabpanel"
              aria-labelledby="tab-compare"
              className="compare-content"
            >
              <div className="section-line">
                <div>
                  <h2>Compare saved runs</h2>
                  <p>Inspect the methods and grids before interpreting a difference.</p>
                </div>
              </div>
              <label className="comparison-selector">
                Comparison run
                <select
                  aria-label="Comparison run"
                  value={comparison?.id ?? ''}
                  onChange={(e) => void chooseComparison(e.target.value)}
                >
                  <option value="">Choose a completed run</option>
                  {history
                    .filter((r) => r.id !== runId && r.status === 'completed')
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.config.name}, {item.id.slice(0, 8)}
                      </option>
                    ))}
                </select>
              </label>
              {comparison &&
              run &&
              rows.length &&
              comparisonRows.length &&
              (!physical || comparisonUnits.units) ? (
                <>
                  <div className="comparison-cards">
                    {[run, comparison].map((item, i) => (
                      <article key={item.id}>
                        <span>{i ? 'Comparison' : 'Current run'}</span>
                        <h3>{item.config.name}</h3>
                        <p>
                          {displayName(item.config.solver.method)} / {item.config.solver.kinetic}
                        </p>
                        <p>
                          {item.config.grid.points.join(' × ')} points, Δt {item.config.solver.dt}
                        </p>
                        <code>{item.id}</code>
                      </article>
                    ))}
                  </div>
                  {(run.config.solver.kinetic !== comparison.config.solver.kinetic ||
                    JSON.stringify(run.config.grid) !== JSON.stringify(comparison.config.grid) ||
                    JSON.stringify(run.config.potential) !==
                      JSON.stringify(comparison.config.potential) ||
                    JSON.stringify(run.config.boundary) !==
                      JSON.stringify(comparison.config.boundary) ||
                    JSON.stringify(run.config.state) !==
                      JSON.stringify(comparison.config.state)) && (
                    <div className="comparison-warning">
                      The grid, kinetic operator, potential, boundary treatment, or initial state
                      differs. This is not a matched integrator comparison; differences cannot be
                      attributed solely to time integration.
                    </div>
                  )}
                  <label className="comparison-selector">
                    Observable
                    <select
                      aria-label="Compare observable"
                      value={selectedDiag}
                      onChange={(e) => setDiagnostic(e.target.value)}
                    >
                      {diagnostics.map((key) => (
                        <option value={key} key={key}>
                          {displayName(key)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <LinePlot
                    height={280}
                    xLabel={physical ? 'Time (fs)' : 'Time (dimensionless)'}
                    yLabel={`${displayName(selectedDiag)} (core units)`}
                    series={[
                      {
                        x: rows.map((r) => (r.time ?? r.t ?? 0) * (physical ? units.time_fs : 1)),
                        y: rows.map((r) => r[selectedDiag] ?? null),
                        label: 'Current run',
                      },
                      {
                        x: comparisonRows.map(
                          (r) =>
                            (r.time ?? r.t ?? 0) *
                            (physical ? (comparisonUnits.units?.time_fs ?? 1) : 1),
                        ),
                        y: comparisonRows.map((r) => r[selectedDiag] ?? null),
                        label: 'Comparison run',
                        color: 'var(--plot-reference)',
                      },
                    ]}
                  />
                  <p className="field-note">
                    These traces are inspectable comparisons, not an automated validation verdict.
                    Compare convergence at matched error and record boundary/domain differences.
                  </p>
                </>
              ) : (
                <div className="tab-empty">
                  <ArrowLeftRight size={32} />
                  <h3>
                    {comparisonLoading || (physical && comparisonUnits.checking)
                      ? 'Loading comparison…'
                      : comparisonUnits.error
                        ? 'Comparison units unavailable'
                        : 'Put two results side by side'}
                  </h3>
                  {comparisonUnits.error && <p role="alert">{comparisonUnits.error}</p>}
                  <p>Load a current run and select another completed run above.</p>
                </div>
              )}
            </section>
          )}

          {tab === 'review' && config && (
            <section id="panel-review" role="tabpanel" aria-labelledby="tab-review">
              <Review config={config} preset={preset} />
            </section>
          )}

          {(run?.warnings?.length ?? 0) > 0 && (
            <div className="run-warnings">
              <h3>Run diagnostics</h3>
              {run?.warnings?.map((w) => (
                <p key={w}>{w}</p>
              ))}
            </div>
          )}
          {run?.error && (
            <div className="error-banner" role="alert">
              Worker failed: {run.error}
            </div>
          )}
          <footer className="run-bar">
            {!showParameters && errors.length > 0 && (
              <div className="config-errors" role="alert">
                {errors.map((message) => (
                  <p key={message}>{message}</p>
                ))}
              </div>
            )}
            <div className="run-bar-info">
              {running ? (
                <>
                  <span>
                    {run?.status === 'finalizing'
                      ? 'Finalizing scientific artifacts'
                      : 'Propagating state'}
                  </span>
                  <strong>{Math.round((run?.progress ?? 0) * 100)}%</strong>
                </>
              ) : (
                <>
                  <Layers3 size={15} />
                  <span>{config?.grid.points.join(' × ') ?? '—'} points</span>
                  <span>
                    {config
                      ? Math.ceil(config.solver.duration / config.solver.dt).toLocaleString()
                      : '—'}{' '}
                    steps
                  </span>
                </>
              )}
              {running && (
                <div
                  className="run-progress"
                  style={{ transform: `scaleX(${Math.max(0, Math.min(1, run?.progress ?? 0))})` }}
                />
              )}
            </div>
            <div className="run-actions">
              <input
                type="file"
                accept="application/json,.json"
                ref={imported}
                hidden
                onChange={(e) => {
                  if (e.target.files?.[0]) void importConfig(e.target.files[0]);
                  e.target.value = '';
                }}
              />
              <button
                type="button"
                className="text-button import-button"
                disabled={running || starting}
                onClick={() => imported.current?.click()}
              >
                <FileJson size={14} />
                Import
              </button>
              <div className="export-control">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!config}
                  aria-expanded={exportOpen}
                  onClick={() => setExportOpen(!exportOpen)}
                >
                  <ArrowDownToLine size={14} />
                  Export
                  <ChevronDown size={12} />
                </button>
                {exportOpen && (
                  <div className="export-menu">
                    <button
                      type="button"
                      onClick={() => {
                        if (config) downloadConfig(config);
                        setExportOpen(false);
                      }}
                    >
                      Configuration JSON
                    </button>
                    {runId &&
                      !running &&
                      ['observables.csv', 'state.h5', 'manifest.json', 'report.html'].map(
                        (name) => (
                          <a
                            key={name}
                            href={artifact(name)}
                            download
                            onClick={() => setExportOpen(false)}
                          >
                            {name === 'state.h5'
                              ? 'Scientific wavefunctions (HDF5)'
                              : name === 'report.html'
                                ? 'Run report (HTML)'
                                : name === 'manifest.json'
                                  ? 'Provenance manifest'
                                  : 'Observables CSV'}
                          </a>
                        ),
                      )}
                  </div>
                )}
              </div>
              {running ? (
                <button
                  type="button"
                  className="primary-button cancel-button"
                  disabled={run?.status === 'finalizing'}
                  onClick={() => void cancel()}
                >
                  <Square size={13} fill="currentColor" />
                  Cancel run
                </button>
              ) : (
                <button
                  type="button"
                  className="primary-button"
                  disabled={
                    !canonicalDraft.resolved ||
                    checking ||
                    errors.length > 0 ||
                    starting ||
                    !connected
                  }
                  onClick={() => void start()}
                >
                  <Play size={14} fill="currentColor" />
                  {starting ? 'Starting…' : checking ? 'Checking draft…' : 'Run simulation'}
                </button>
              )}
            </div>
          </footer>
        </main>
        {showParameters && config && (
          <ConfigPanel
            config={config}
            onChange={setConfig}
            units={draftUnits.units}
            errors={errors}
            checking={checking}
            disabled={running || starting}
          />
        )}
      </div>
      <div className="bottom-status">
        <span>
          <Check size={11} />
          One numerical engine for CLI, browser and notebooks
        </span>
        <span>Static single-particle TDSE, initial normalisation only</span>
      </div>
    </div>
  );
}
