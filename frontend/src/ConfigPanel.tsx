import { ChevronDown, Settings2 } from 'lucide-react';
import { useId, useState } from 'react';
import type { Config, UnitScales } from './types';
import { CORE_UNITS, displayName } from './types';

function NumberInput({
  label,
  value,
  onChange,
  min,
  step = 'any',
  suffix,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  step?: number | 'any';
  suffix?: string;
}) {
  const id = useId();
  return (
    <label className="number-field" htmlFor={id}>
      <span>
        {label}
        {suffix && <small>{suffix}</small>}
      </span>
      <input
        id={id}
        type="number"
        value={Number.isFinite(value) ? Number(value.toPrecision(10)) : ''}
        min={min}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function Group({
  title,
  children,
  open = false,
}: {
  title: string;
  children: React.ReactNode;
  open?: boolean;
}) {
  return (
    <details className="config-group" open={open}>
      <summary>
        {title}
        <ChevronDown size={14} />
      </summary>
      <div className="group-fields">{children}</div>
    </details>
  );
}

function JsonParams({
  value,
  onChange,
}: {
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const [error, setError] = useState('');
  return (
    <>
      <label className="select-field">
        Advanced state parameters (JSON)
        <textarea
          className="advanced-json"
          key={JSON.stringify(value)}
          defaultValue={JSON.stringify(value, null, 2)}
          onBlur={(e) => {
            try {
              const parsed = JSON.parse(e.target.value);
              if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
                throw new Error('Parameters must be a JSON object.');
              onChange(parsed);
              setError('');
            } catch (e) {
              setError(
                `Not applied; the last valid state parameters are retained. ${(e as Error).message}`,
              );
            }
          }}
        />
      </label>
      {error && (
        <p className="json-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function UnitInputs({
  config,
  change,
}: {
  config: Config;
  change: (mutate: (c: Config) => void) => void;
}) {
  return (
    <>
      {' '}
      <label className="select-field">
        Draft input units
        <select
          aria-label="Unit system"
          value={config.units.mode}
          onChange={(e) =>
            change((c) => {
              c.units.mode = e.target.value as Config['units']['mode'];
            })
          }
        >
          <option value="dimensionless">Dimensionless (ℏ = m = 1)</option>
          <option value="electron">Electron (nm / fs / eV)</option>
        </select>
      </label>
      {config.units.mode === 'electron' && (
        <NumberInput
          label="Reference length"
          value={config.units.length_nm}
          min={0}
          suffix="nm"
          onChange={(v) =>
            change((c) => {
              c.units.length_nm = v;
            })
          }
        />
      )}
    </>
  );
}

function DraftStatus({ errors, checking }: { errors: string[]; checking: boolean }) {
  return (
    <>
      {checking && (
        <p className="field-note" role="status">
          Checking the draft with the numerical engine…
        </p>
      )}
      {errors.length > 0 && (
        <div className="config-errors" role="alert">
          {errors.map((error) => (
            <p key={error}>{error}</p>
          ))}
        </div>
      )}
    </>
  );
}
export default function ConfigPanel({
  config,
  onChange,
  units: metadata,
  disabled,
  errors,
  checking,
}: {
  config: Config;
  onChange: (next: Config) => void;
  units: UnitScales | null;
  disabled: boolean;
  errors: string[];
  checking: boolean;
}) {
  const change = (mutate: (c: Config) => void) => {
    const c = structuredClone(config);
    mutate(c);
    onChange(c);
  };
  const physical = config.units.mode === 'electron';
  if (physical && !metadata)
    return (
      <aside className="parameters-panel" aria-label="Simulation parameters">
        <div className="panel-heading">
          <Settings2 size={15} />
          <h2>Parameters</h2>
        </div>
        <fieldset disabled={disabled} className="config-fieldset">
          <Group title="Grid & units" open>
            <UnitInputs config={config} change={change} />
            <p className="field-note">
              Physical input conversion is unavailable until the server supplies valid unit
              metadata. Correct the reference length or choose dimensionless inputs.
            </p>
          </Group>
        </fieldset>
        <DraftStatus errors={errors} checking={checking} />
      </aside>
    );
  const units = metadata ?? CORE_UNITS;
  const l = physical ? units.length_nm : 1,
    t = physical ? units.time_fs : 1;
  const axis = ['x', 'y'];
  const steps = Math.ceil(config.solver.duration / config.solver.dt);
  const total = config.grid.points.reduce((a, b) => a * b, 1);
  const outputMB = (total * config.sampling.snapshots * 16) / 2 ** 20;
  const parameterFactor = (key: string) => {
    if (!physical) return { factor: 1, unit: '' };
    if (key === 'omega') return { factor: units.current_per_fs, unit: 'fs⁻¹' };
    if (key === 'height') return { factor: units.energy_ev, unit: 'eV' };
    if (key === 'tilt') return { factor: units.energy_ev / l, unit: 'eV/nm' };
    if (
      [
        'width',
        'radius',
        'separation',
        'slit_width',
        'slit_separation',
        'thickness',
        'center',
        'xcenter',
        'center_y',
        'bend_x',
        'smoothing',
        'sigma',
      ].includes(key)
    )
      return { factor: l, unit: 'nm' };
    if (key === 'angle') return { factor: 1, unit: 'rad' };
    return { factor: 1, unit: 'dimensionless' };
  };
  return (
    <aside className="parameters-panel" aria-label="Simulation parameters">
      <div className="panel-heading">
        <Settings2 size={15} />
        <h2>Parameters</h2>
        <span className="muted-label">{disabled ? 'run in progress' : 'editable'}</span>
      </div>
      <fieldset disabled={disabled} className="config-fieldset">
        <Group title="Evolution" open>
          <label className="select-field">
            Propagator
            <select
              aria-label="Propagator"
              value={config.solver.method}
              onChange={(e) =>
                change((c) => {
                  c.solver.method = e.target.value as Config['solver']['method'];
                  if (c.solver.method === 'cn') c.solver.kinetic = 'fd2';
                })
              }
            >
              <option value="strang">Strang (second order)</option>
              <option value="yoshida4">Yoshida (fourth order)</option>
              <option value="cn" disabled={config.grid.points.length === 2}>
                Crank-Nicolson (1D)
              </option>
            </select>
          </label>
          <label className="select-field">
            Kinetic discretisation
            <select
              aria-label="Kinetic discretisation"
              value={config.solver.kinetic}
              disabled={config.solver.method === 'cn'}
              onChange={(e) =>
                change((c) => {
                  c.solver.kinetic = e.target.value as Config['solver']['kinetic'];
                })
              }
            >
              <option value="spectral">Fourier spectral</option>
              <option value="fd2">Matched finite difference (FD2)</option>
            </select>
          </label>
          <div className="field-pair">
            <NumberInput
              label="Timestep"
              value={config.solver.dt * t}
              min={0}
              suffix={physical ? 'fs' : 'Δt'}
              onChange={(v) =>
                change((c) => {
                  c.solver.dt = v / t;
                })
              }
            />
            <NumberInput
              label="Duration"
              value={config.solver.duration * t}
              min={0}
              suffix={physical ? 'fs' : 'T'}
              onChange={(v) =>
                change((c) => {
                  c.solver.duration = v / t;
                })
              }
            />
          </div>
          <p className="field-note">
            Accuracy depends on both the grid and timestep. A conserved norm is not an accuracy
            certificate.
          </p>
        </Group>
        <Group title="Grid & units" open>
          <UnitInputs config={config} change={change} />
          {config.grid.points.map((n, i) => (
            <div key={axis[i]} className="axis-group">
              <span className="axis-title">{axis[i]} axis</span>
              <NumberInput
                label="Grid points"
                value={n}
                min={16}
                step={1}
                onChange={(v) =>
                  change((c) => {
                    c.grid.points[i] = v;
                  })
                }
              />
              <div className="field-pair">
                <NumberInput
                  label="Minimum"
                  value={config.grid.bounds[i][0] * l}
                  suffix={physical ? 'nm' : ''}
                  onChange={(v) =>
                    change((c) => {
                      c.grid.bounds[i][0] = v / l;
                    })
                  }
                />
                <NumberInput
                  label="Maximum"
                  value={config.grid.bounds[i][1] * l}
                  suffix={physical ? 'nm' : ''}
                  onChange={(v) =>
                    change((c) => {
                      c.grid.bounds[i][1] = v / l;
                    })
                  }
                />
              </div>
            </div>
          ))}
          <p className="field-note">
            The endpoint is excluded. Fourier evolution is periodic; absorbing layers approximate an
            open domain.
          </p>
        </Group>
        <Group title="Initial state">
          <div className="state-type">{displayName(config.state.kind)}</div>
          {['sum', 'eigen_superposition'].includes(config.state.kind) && (
            <p className="field-note">
              This state is defined by its component states or eigenstate coefficients below. The
              top-level packet centre and width do not define it.
            </p>
          )}
          {!['sum', 'eigen_superposition'].includes(config.state.kind) &&
            config.grid.points.map((_, i) => (
              <div key={axis[i]} className="axis-group">
                <span className="axis-title">{axis[i]} component</span>
                <NumberInput
                  label="Centre"
                  value={(config.state.center[i] ?? 0) * l}
                  suffix={physical ? 'nm' : ''}
                  onChange={(v) =>
                    change((c) => {
                      c.state.center[i] = v / l;
                    })
                  }
                />
                <div className="field-pair">
                  <NumberInput
                    label="Wave number"
                    value={(config.state.momentum[i] ?? 0) / l}
                    suffix={physical ? 'nm⁻¹' : 'k'}
                    onChange={(v) =>
                      change((c) => {
                        c.state.momentum[i] = v * l;
                      })
                    }
                  />
                  {!config.state.kind.startsWith('ho_') &&
                    !(config.state.kind === 'waveguide_mode' && i === 1) && (
                      <NumberInput
                        label="Density width"
                        value={(config.state.sigma[i] ?? 1) * l}
                        min={0}
                        suffix={physical ? 'nm' : 'σ'}
                        onChange={(v) =>
                          change((c) => {
                            c.state.sigma[i] = v / l;
                          })
                        }
                      />
                    )}
                </div>
              </div>
            ))}
          {config.state.kind.startsWith('ho_') && (
            <p className="field-note">
              Oscillator widths are determined by omega and squeeze in the state parameters. Match
              the state and potential frequencies intentionally.
            </p>
          )}
          <NumberInput
            label="Global phase"
            value={config.state.phase ?? 0}
            suffix="rad"
            onChange={(v) =>
              change((c) => {
                c.state.phase = v;
              })
            }
          />
          {Object.entries(config.state.params ?? {}).map(([key, value]) =>
            typeof value === 'number' ? (
              <NumberInput
                key={key}
                label={displayName(key)}
                value={value}
                suffix="core units"
                onChange={(v) =>
                  change((c) => {
                    c.state.params[key] = v;
                  })
                }
              />
            ) : null,
          )}
          <JsonParams
            value={config.state.params ?? {}}
            onChange={(v) =>
              change((c) => {
                c.state.params = v;
              })
            }
          />
          <p className="field-note">
            Advanced state JSON uses dimensionless core units, including nested packet components
            and oscillator frequencies. The server validates the resolved state.
          </p>
        </Group>
        <Group title="Potential">
          <div className="state-type">{displayName(config.potential.kind)}</div>
          {Object.entries(config.potential.params ?? {}).length === 0 && (
            <p className="field-note">Free propagation: V = 0 everywhere.</p>
          )}
          {Object.entries(config.potential.params ?? {}).map(([key, value]) => {
            const { factor, unit } = parameterFactor(key);
            if (typeof value === 'number')
              return (
                <NumberInput
                  key={key}
                  label={displayName(key)}
                  value={value * factor}
                  suffix={unit}
                  onChange={(v) =>
                    change((c) => {
                      c.potential.params[key] = v / factor;
                    })
                  }
                />
              );
            if (Array.isArray(value) && value.every((v) => typeof v === 'number'))
              return value.map((v, i) => (
                <NumberInput
                  key={`${key}${axis[i] ?? i + 1}`}
                  label={`${displayName(key)} ${i + 1}`}
                  value={v * factor}
                  suffix={unit}
                  onChange={(v) =>
                    change((c) => {
                      (c.potential.params[key] as number[])[i] = v / factor;
                    })
                  }
                />
              ));
            return null;
          })}
        </Group>
        <Group title="Boundary treatment">
          <label className="select-field">
            Boundary model
            <select
              aria-label="Boundary treatment"
              value={config.boundary.kind}
              onChange={(e) =>
                change((c) => {
                  c.boundary.kind = e.target.value as Config['boundary']['kind'];
                })
              }
            >
              <option value="periodic">Periodic, closed</option>
              <option value="cap">Complex absorbing layer</option>
            </select>
          </label>
          {config.boundary.kind === 'cap' && (
            <>
              <NumberInput
                label="Layer width"
                value={config.boundary.width * l}
                min={0}
                suffix={physical ? 'nm' : ''}
                onChange={(v) =>
                  change((c) => {
                    c.boundary.width = v / l;
                  })
                }
              />
              <NumberInput
                label="Absorber strength"
                value={config.boundary.strength * (physical ? units.energy_ev : 1)}
                min={0}
                suffix={physical ? 'eV' : ''}
                onChange={(v) =>
                  change((c) => {
                    c.boundary.strength = v / (physical ? units.energy_ev : 1);
                  })
                }
              />
              <NumberInput
                label="Polynomial power"
                value={config.boundary.power}
                min={2}
                step={1}
                onChange={(v) =>
                  change((c) => {
                    c.boundary.power = v;
                  })
                }
              />
            </>
          )}
          <p className="field-note">
            Absorbers intentionally remove probability. Their reflection must be calibrated
            separately from loss accounting.
          </p>
        </Group>
        <Group title="Measurements & saved data">
          {config.grid.points.length === 2 && (
            <>
              <label className="inline-check screen-enabled">
                <input
                  type="checkbox"
                  checked={config.sampling.screen_x != null}
                  onChange={(e) =>
                    change((c) => {
                      c.sampling.screen_x = e.target.checked
                        ? c.grid.bounds[0][0] + 0.75 * (c.grid.bounds[0][1] - c.grid.bounds[0][0])
                        : null;
                    })
                  }
                />
                Record a screen profile
              </label>
              {config.sampling.screen_x != null && (
                <NumberInput
                  label="Screen position x"
                  value={config.sampling.screen_x * l}
                  suffix={physical ? 'nm' : ''}
                  onChange={(v) =>
                    change((c) => {
                      c.sampling.screen_x = v / l;
                    })
                  }
                />
              )}
              <p className="field-note">
                The screen records signed time-integrated current and density separately. It is a
                diagnostic plane, not a detector-collapse model.
              </p>
            </>
          )}
          <NumberInput
            label="Scientific snapshots"
            value={config.sampling.snapshots}
            min={2}
            step={1}
            onChange={(v) =>
              change((c) => {
                c.sampling.snapshots = v;
              })
            }
          />
          <NumberInput
            label="Observe every n steps"
            value={config.sampling.observable_every}
            min={1}
            step={1}
            onChange={(v) =>
              change((c) => {
                c.sampling.observable_every = v;
              })
            }
          />
          <div className="budget-summary">
            <span>{Number.isFinite(steps) ? steps.toLocaleString() : '—'} steps</span>
            <span>{total.toLocaleString()} points</span>
            <span>~{outputMB.toFixed(1)} MiB snapshots</span>
          </div>
          <p className="field-note">
            The server performs authoritative resource checks. It never silently coarsens your
            simulation.
          </p>
        </Group>
      </fieldset>
      <DraftStatus errors={errors} checking={checking} />
    </aside>
  );
}
