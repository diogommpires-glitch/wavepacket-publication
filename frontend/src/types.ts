import type { components } from './generated/api';

// Pydantic resolves every default before a configuration enters the editable UI.
// OpenAPI also describes partial request inputs, so those optional fields become required here.
type Resolved<T> = T extends readonly unknown[]
  ? T
  : T extends object
    ? { [K in keyof T]-?: Resolved<T[K]> }
    : T;
export type Config = Resolved<components['schemas']['SimulationConfig']>;
export type Preset = components['schemas']['PresetRecord'] & { config: Config };
export type ValidationReport = components['schemas']['ValidationReport'];
export type Run = components['schemas']['RunRecord'] & { config: Config };
export type Frame = components['schemas']['Frame'];
export type Values = Frame['density'];
export type Row = Frame['observables'];
export type UnitScales = Pick<
  components['schemas']['UnitScalesRecord'],
  | 'length_nm'
  | 'time_fs'
  | 'energy_ev'
  | 'momentum_inverse_nm'
  | 'density_per_nm'
  | 'density_per_nm2'
  | 'current_per_fs'
  | 'current_per_nm_fs'
>;
// Identity factors are used only while displaying dimensionless core values.
export const CORE_UNITS: UnitScales = {
  length_nm: 1,
  time_fs: 1,
  energy_ev: 1,
  momentum_inverse_nm: 1,
  density_per_nm: 1,
  density_per_nm2: 1,
  current_per_fs: 1,
  current_per_nm_fs: 1,
};
export type ViewMode = 'density' | 'phase' | 'current';
export const activeRun = (run?: Run | null) =>
  run?.status === 'running' || run?.status === 'queued' || run?.status === 'finalizing';
export const displayName = (s: string) => s.replaceAll('_', ' ').replaceAll('-', ' ');

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let detail: unknown;
    const body = await response.text();
    try {
      detail = JSON.parse(body);
    } catch {
      detail = body;
    }
    const d = detail as { detail?: unknown };
    throw new ApiError(
      typeof d?.detail === 'string'
        ? d.detail
        : JSON.stringify(d?.detail ?? detail) || response.statusText,
      response.status,
    );
  }
  if (response.status === 204) throw new Error('No preview yet');
  return response.json() as Promise<T>;
}
