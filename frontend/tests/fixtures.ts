import type { Config, Frame, Preset, Run, UnitScales } from '../src/types';

// Deliberately artificial canonical metadata: UI tests must use server factors, not physical constants.
export function testUnits(length = 1): UnitScales {
  const time = 5 * length * length;
  return {
    length_nm: length,
    time_fs: time,
    energy_ev: 2 / (length * length),
    momentum_inverse_nm: 1 / length,
    density_per_nm: 1 / length,
    density_per_nm2: 1 / (length * length),
    current_per_fs: 1 / time,
    current_per_nm_fs: 1 / (time * length),
  };
}

export const config: Config = {
  schema_version: 1,
  name: 'test-free',
  grid: { bounds: [[-4, 4]], points: [32] },
  state: { kind: 'gaussian', center: [-1], momentum: [1], sigma: [1], phase: 0, params: {} },
  potential: { kind: 'free', params: {} },
  solver: { method: 'strang', kinetic: 'spectral', dt: 0.01, duration: 1 },
  boundary: { kind: 'periodic', width: 1, strength: 1, power: 4 },
  sampling: { observable_every: 10, snapshots: 3, screen_x: null },
  budget: {
    max_working_bytes: 536870912,
    max_steps: 200000,
    max_points: 262144,
    max_snapshots: 128,
    max_output_bytes: 1073741824,
  },
  units: { mode: 'dimensionless', length_nm: 1 },
};

export const presets: Preset[] = [
  {
    id: 'test-free',
    name: 'Test free packet',
    dimension: 1,
    question: 'Does free propagation agree?',
    evidence: 'analytic',
    title: 'Test free packet',
    scientific_question: 'Does free propagation agree?',
    validation_status: 'report_required',
    evidence_record: {
      configuration_sha256: 'a'.repeat(64),
      status: 'report_required',
      check_ids: ['free-packet'],
      scope: 'Exact fixture only',
      conditions: { dt: 0.01 },
    },
    limitations: [],
    config,
  },
  {
    id: 'test-trap',
    name: 'Test trapped packet',
    dimension: 1,
    question: 'Does the trap agree?',
    evidence: 'analytic',
    title: 'Test trapped packet',
    scientific_question: 'Does the trap agree?',
    validation_status: 'report_required',
    evidence_record: {
      configuration_sha256: 'b'.repeat(64),
      status: 'report_required',
      check_ids: ['harmonic'],
      scope: 'Exact fixture only',
      conditions: { dt: 0.01 },
    },
    limitations: [],
    config: { ...config, name: 'test-trap' },
  },
];

export function savedRun(id: string, name = id, overrides: Partial<Config> = {}): Run {
  return {
    schema_version: 2,
    scientific_status: 'complete',
    report_status: 'complete',
    id,
    status: 'completed',
    progress: 1,
    created_at: '2026-10-28T12:00:00Z',
    config: { ...structuredClone(config), name, ...overrides },
  };
}

export const frame: Frame = {
  current_location: 'node',
  density_scale_max: 0.8,
  density_scale_scope: 'max_across_saved_frames',
  step: 100,
  total_steps: 100,
  time: 1,
  dimension: 1,
  shape: [3],
  axes: { x: [-1, 0, 1] },
  density: [0.1, 0.8, 0.1],
  phase: [0, 0, 0],
  potential: [0, 0, 0],
  current_x: [0, 0, 0],
  observables: { norm: 1, energy: 1, x_mean: 0, edge_probability: 0 },
};

export function field2d(density: number[][]): Frame {
  return {
    current_location: 'node',
    density_scale_max: Math.max(...density.flat()),
    density_scale_scope: 'max_across_saved_frames',
    step: 100,
    total_steps: 100,
    time: 1,
    dimension: 2,
    shape: [2, 2],
    axes: { x: [0, 1], y: [0, 1] },
    density,
    phase: [
      [0, 0],
      [0, 0],
    ],
    potential: [
      [0, 0],
      [0, 0],
    ],
    current_x: [
      [0, 0],
      [0, 0],
    ],
    observables: { norm: density.flat().reduce((a, b) => a + b, 0) },
  };
}
