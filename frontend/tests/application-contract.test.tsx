import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import type { Config, Run } from '../src/types';
import { config, frame, presets, savedRun, testUnits } from './fixtures';

const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

function mockEngine(
  options: {
    runs?: Run[];
    comparisonB?: Promise<Response>;
    comparisonC?: Promise<Response>;
    frame?: typeof frame;
    frames?: (typeof frame)[];
    start?: Response;
    resolve?: (value: Config) => Response | Promise<Response>;
    units?: (length: number) => Response | Promise<Response>;
    status?: (id: string) => Response | Promise<Response>;
    frameList?: (id: string) => Response | Promise<Response>;
    observables?: (id: string) => Response | Promise<Response>;
  } = {},
) {
  const runs = options.runs ?? [];
  return vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/presets') return response(presets);
      if (url === '/api/runs')
        return init?.method === 'POST' && options.start ? options.start : response(runs);
      if (url.startsWith('/api/units')) {
        const length = Number(new URL(url, 'http://localhost').searchParams.get('length_nm'));
        return options.units?.(length) ?? response(testUnits(length));
      }
      if (url === '/api/config/resolve') {
        const value = JSON.parse(String(init?.body)) as Config;
        return options.resolve?.(value) ?? response(value);
      }
      const id = url.split('/')[3];
      if (url.endsWith('/observables')) {
        if (options.observables) return options.observables(id);
        if (id === 'b' && options.comparisonB) return options.comparisonB;
        if (id === 'c' && options.comparisonC) return options.comparisonC;
        return response([
          { time: 0, energy: id === 'c' ? 3 : 1, norm: 1 },
          { time: 1, energy: id === 'c' ? 3 : 1, norm: 1 },
        ]);
      }
      if (url.endsWith('/frames'))
        return (
          options.frameList?.(id) ??
          response(
            options.frames?.map((saved, index) => ({ index, time: saved.time })) ?? [
              { index: 0, time: 0 },
              { index: 1, time: 1 },
            ],
          )
        );
      if (url.includes('/frames/') && options.frames)
        return response(options.frames[Number(url.split('/').at(-1))]);
      if (url.includes('/frames/') || url.endsWith('/preview'))
        return response(options.frame ?? frame);
      return (
        options.status?.(id) ?? response(runs.find((run) => run.id === id) ?? { status: 'not_run' })
      );
    }),
  );
}

async function ready() {
  render(<App />);
  await screen.findByRole('heading', { name: 'Test free packet' });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Run simulation' })).toBeEnabled());
}

it('shows Wavepacket as the home link name', async () => {
  mockEngine();
  await ready();
  expect(screen.getByRole('link', { name: 'Wavepacket home' })).toHaveTextContent(/^Wavepacket$/);
});

describe('configuration imports', () => {
  it('applies only the canonical resolved configuration, including missing defaults', async () => {
    mockEngine({ resolve: () => response(config) });
    await ready();
    const partial = JSON.parse(JSON.stringify(config)) as { state: Record<string, unknown> };
    delete partial.state.center;
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(
      input,
      new File([JSON.stringify(partial)], 'partial.json', { type: 'application/json' }),
    );
    await screen.findByRole('heading', { name: config.name });
    expect(fetch).toHaveBeenCalledWith(
      '/api/config/resolve',
      expect.objectContaining({ body: JSON.stringify(partial) }),
    );
    expect(document.querySelector('.application')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('retains the mounted application and previous draft when the server rejects imported data', async () => {
    mockEngine({
      resolve: (value) =>
        value.state.center === null
          ? response({ detail: 'state.center must be a finite vector' }, 422)
          : response(value),
    });
    await ready();
    const malformed = { ...config, state: { ...config.state, center: null } };
    await userEvent.upload(
      document.querySelector<HTMLInputElement>('input[type="file"]')!,
      new File([JSON.stringify(malformed)], 'invalid.json', { type: 'application/json' }),
    );
    await screen.findByRole('alert');
    expect(screen.getByRole('heading', { name: 'Test free packet' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('state.center');
  });
});

describe('saved-run identity', () => {
  it('navigates saved frames with boundary controls and pauses replay when stepping manually', async () => {
    mockEngine({
      runs: [savedRun('a', 'Replay source')],
      frames: [0, 1, 2].map((index) => ({
        ...frame,
        time: index / 2,
        observables: { ...frame.observables, energy: index + 1 },
      })),
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Replay source/ }));
    const slider = await screen.findByLabelText('Saved frame');
    const first = screen.getByRole('button', { name: 'First saved frame' });
    const previous = screen.getByRole('button', { name: 'Previous saved frame' });
    const next = screen.getByRole('button', { name: 'Next saved frame' });
    const last = screen.getByRole('button', { name: 'Last saved frame' });
    const expectFrame = async (index: number) => {
      expect(slider).toHaveValue(String(index));
      await waitFor(() =>
        expect(document.querySelector('.metric-strip > div:nth-child(2) strong')).toHaveTextContent(
          `${index + 1} (dimensionless)`,
        ),
      );
    };

    await expectFrame(2);
    expect(next).toBeDisabled();
    expect(last).toBeDisabled();
    await userEvent.click(first);
    await expectFrame(0);
    expect(first).toBeDisabled();
    expect(previous).toBeDisabled();
    await userEvent.click(next);
    await expectFrame(1);
    expect(first).toBeEnabled();
    expect(previous).toBeEnabled();
    expect(next).toBeEnabled();
    expect(last).toBeEnabled();
    await userEvent.click(last);
    await expectFrame(2);
    await userEvent.click(previous);
    await expectFrame(1);
    await userEvent.click(first);
    await expectFrame(0);

    fireEvent.click(screen.getByRole('button', { name: 'Play replay' }));
    expect(screen.getByRole('button', { name: 'Pause replay' })).toBeInTheDocument();
    fireEvent.click(next);
    await expectFrame(1);
    expect(screen.getByRole('button', { name: 'Play replay' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pause replay' })).not.toBeInTheDocument();
  });

  it('ignores a late comparison response after another run is selected', async () => {
    let finishB!: (value: Response) => void;
    const comparisonB = new Promise<Response>((resolve) => {
      finishB = resolve;
    });
    mockEngine({
      runs: [
        savedRun('a', 'Current source'),
        savedRun('b', 'Older comparison'),
        savedRun('c', 'Selected comparison'),
      ],
      comparisonB,
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Current source/ }));
    await screen.findByLabelText('Saved frame');
    await userEvent.click(screen.getByRole('tab', { name: 'Compare' }));
    await userEvent.selectOptions(screen.getByLabelText('Comparison run', { exact: true }), 'b');
    await userEvent.selectOptions(screen.getByLabelText('Comparison run', { exact: true }), 'c');
    await screen.findByRole('heading', { name: 'Selected comparison' });
    await userEvent.selectOptions(screen.getByLabelText('Compare observable'), 'energy');
    fireEvent.mouseMove(document.querySelector('.compare-content svg')!, { clientX: 100 });
    await waitFor(() =>
      expect(
        document.querySelector('.compare-content .plot-legend > span:last-child b'),
      ).toHaveTextContent('3'),
    );
    await act(async () => {
      finishB(
        response([
          { time: 0, energy: 7, norm: 1 },
          { time: 1, energy: 7, norm: 1 },
        ]),
      );
    });
    expect(
      document.querySelector('.compare-content .plot-legend > span:last-child b'),
    ).toHaveTextContent('3');
  });

  it('keeps result physical scales bound to the saved run while editing the next draft', async () => {
    mockEngine({
      runs: [savedRun('a', 'Electron source', { units: { mode: 'electron', length_nm: 1 } })],
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Electron source/ }));
    await screen.findByLabelText('Saved frame');
    const before = document.querySelector('.metric-strip > div:nth-child(2) strong')!.textContent;
    expect(before).toContain('2 eV');
    fireEvent.change(screen.getByLabelText(/^Reference length/), { target: { value: '2' } });
    await act(async () => {});
    expect(document.querySelector('.metric-strip > div:nth-child(2) strong')!.textContent).toBe(
      before,
    );
  });

  it('locates FD2 current on source-grid half-faces even when preview axes are coarse', async () => {
    mockEngine({
      runs: [
        savedRun('a', 'FD2 source', {
          solver: { ...config.solver, kinetic: 'fd2' },
          units: { mode: 'electron', length_nm: 2 },
        }),
      ],
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /FD2 source/ }));
    await screen.findByLabelText('Saved frame');
    await userEvent.click(screen.getByLabelText('Potential overlay'));
    await userEvent.click(screen.getByRole('button', { name: 'jₓ Current' }));
    // Source Δx=8/32, preview Δx=1. The first face is (-1+Δx/2)*L₀ = -1.75nm.
    expect(document.querySelector('.field-stage svg')).toHaveTextContent('-1.75');
    fireEvent.change(screen.getByLabelText('Grid points'), { target: { value: '64' } });
    expect(document.querySelector('.field-stage svg')).toHaveTextContent('-1.75');
  });

  it('preserves the saved result when the server rejects a new run before admission', async () => {
    mockEngine({
      runs: [savedRun('a', 'Saved result')],
      start: response({ detail: 'Working memory budget exceeded' }, 422),
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Saved result/ }));
    await screen.findByLabelText('Saved frame');
    const energy = document.querySelector('.metric-strip > div:nth-child(2) strong')!.textContent;
    await userEvent.click(await screen.findByRole('button', { name: 'Run simulation' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent('Working memory budget exceeded');
    expect(screen.getByLabelText('Saved frame')).toBeInTheDocument();
    expect(document.querySelector('.metric-strip > div:nth-child(2) strong')!.textContent).toBe(
      energy,
    );
  });

  it('shows the exact preset fingerprint and withdraws its evidence status for an edited draft', async () => {
    mockEngine();
    await ready();
    await userEvent.click(screen.getByRole('tab', { name: 'Review & theory' }));
    expect(screen.getByText('report required')).toBeInTheDocument();
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Timestep/), { target: { value: '.03' } });
    expect(screen.getByText('edited unverified')).toBeInTheDocument();
    expect(screen.getByText(/current draft differs from this preset hash/)).toBeInTheDocument();
  });

  it('does not attribute an earlier completed request to a still-loading selection', async () => {
    let finishB!: (value: Response) => void;
    let finishC!: (value: Response) => void;
    mockEngine({
      runs: [savedRun('a', 'Current source'), savedRun('b'), savedRun('c', 'Selected comparison')],
      comparisonB: new Promise((resolve) => {
        finishB = resolve;
      }),
      comparisonC: new Promise((resolve) => {
        finishC = resolve;
      }),
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Current source/ }));
    await screen.findByLabelText('Saved frame');
    await userEvent.click(screen.getByRole('tab', { name: 'Compare' }));
    await userEvent.selectOptions(screen.getByLabelText('Comparison run', { exact: true }), 'b');
    await userEvent.selectOptions(screen.getByLabelText('Comparison run', { exact: true }), 'c');
    await act(async () => {
      finishB(response([{ time: 0, energy: 7 }]));
    });
    expect(screen.getByRole('heading', { name: 'Loading comparison…' })).toBeInTheDocument();
    expect(document.querySelector('.compare-content svg[role="img"]')).not.toBeInTheDocument();
    await act(async () => {
      finishC(response([{ time: 0, energy: 3 }]));
    });
    expect(screen.getByRole('heading', { name: 'Selected comparison' })).toBeInTheDocument();
  });

  it('clears comparison identity and ignores pending data when the current experiment changes', async () => {
    let finishB!: (value: Response) => void;
    mockEngine({
      runs: [savedRun('a', 'Current source'), savedRun('b')],
      comparisonB: new Promise((resolve) => {
        finishB = resolve;
      }),
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Current source/ }));
    await screen.findByLabelText('Saved frame');
    await userEvent.click(screen.getByRole('tab', { name: 'Compare' }));
    await userEvent.selectOptions(screen.getByLabelText('Comparison run', { exact: true }), 'b');
    await userEvent.click(screen.getByRole('button', { name: /Test trapped packet/ }));
    await act(async () => {
      finishB(response([{ time: 0, energy: 7 }]));
    });
    expect(screen.getByLabelText('Comparison run', { exact: true })).toHaveValue('');
    expect(document.querySelector('.compare-content svg[role="img"]')).not.toBeInTheDocument();
  });

  it('renders withheld metrics with their reporting reason and disables cancellation during finalization', async () => {
    const finalizing = { ...savedRun('a', 'Finalizing source'), status: 'finalizing' as const };
    mockEngine({
      runs: [finalizing],
      frame: {
        ...frame,
        observables: { ...frame.observables, energy: null, x_mean: null },
        validity: {
          conditional_status: 'below_reporting_floor',
          reporting_floor: 1e-14,
          initial_norm: 1,
          reason: 'Surviving norm is below reporting floor',
        },
      },
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Finalizing source/ }));
    await screen.findByText(/Surviving norm is below reporting floor/);
    expect(document.querySelector('.metric-strip > div:nth-child(2) strong')).toHaveTextContent(
      'Unavailable',
    );
    expect(screen.getByRole('button', { name: 'Cancel run' })).toBeDisabled();
    expect(screen.getByText('Finalizing scientific artifacts')).toBeInTheDocument();
  });
});

describe('authoritative draft validation', () => {
  it('blocks pending or rejected drafts with the server resource reason and retains editable values', async () => {
    mockEngine({
      resolve: (value) =>
        value.grid.points[0] === 128
          ? response({ detail: 'Working memory estimate exceeds max_working_bytes' }, 422)
          : response(value),
    });
    await ready();
    fireEvent.change(screen.getByLabelText('Grid points'), { target: { value: '128' } });
    expect(screen.getByRole('button', { name: 'Checking draft…' })).toBeDisabled();
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Working memory estimate exceeds max_working_bytes',
    );
    expect(screen.getByRole('button', { name: 'Run simulation' })).toBeDisabled();
    expect(screen.getByLabelText('Grid points')).toHaveValue(128);
  });

  it('ignores a late rejected draft response after a newer valid edit', async () => {
    let finishOld!: (value: Response) => void;
    mockEngine({
      resolve: (value) =>
        value.solver.dt === 0.03
          ? new Promise((resolve) => {
              finishOld = resolve;
            })
          : response(value),
    });
    await ready();
    fireEvent.change(screen.getByLabelText(/^Timestep/), { target: { value: '.03' } });
    await waitFor(() => expect(finishOld).toBeTypeOf('function'));
    fireEvent.change(screen.getByLabelText(/^Timestep/), { target: { value: '.01' } });
    expect(screen.getByRole('button', { name: 'Checking draft…' })).toBeDisabled();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Run simulation' })).toBeEnabled(),
    );
    await act(async () => {
      finishOld(response({ detail: 'Obsolete draft rejected' }, 422));
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^Timestep/)).toHaveValue(0.01);
    expect(screen.getByRole('button', { name: 'Run simulation' })).toBeEnabled();
  });

  it('keeps invalid physical-scale inputs correctable without inventing conversion factors', async () => {
    mockEngine({
      units: (length) =>
        length === 2
          ? response({ detail: 'Unit conversion is not representable' }, 422)
          : response(testUnits(length)),
    });
    await ready();
    await userEvent.selectOptions(screen.getByLabelText('Unit system'), 'electron');
    fireEvent.change(screen.getByLabelText(/^Reference length/), { target: { value: '2' } });
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent('Unit conversion is not representable');
    expect(screen.queryByLabelText(/^Timestep/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Reference length/), { target: { value: '1' } });
    await screen.findByLabelText(/^Timestep/);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Run simulation' })).toBeEnabled(),
    );
  });
});

describe('saved-result recovery', () => {
  it('can retry the selected result after its read-error message is dismissed', async () => {
    let frameReads = 0;
    mockEngine({
      runs: [savedRun('a', 'Retry source')],
      frameList: () => {
        frameReads += 1;
        return frameReads === 1
          ? response({ detail: 'Temporary frame read failure' }, 500)
          : response([
              { index: 0, time: 0 },
              { index: 1, time: 1 },
            ]);
      },
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Retry source/ }));
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss run error' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Retry source/ }));

    await screen.findByLabelText('Saved frame');
    expect(frameReads).toBe(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('retains the selected frame and measurements when the current history item is selected again', async () => {
    mockEngine({ runs: [savedRun('a', 'Replay source')] });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Replay source/ }));
    await screen.findByLabelText('Saved frame');
    await userEvent.click(screen.getByRole('button', { name: 'First saved frame' }));
    const energy = document.querySelector('.metric-strip > div:nth-child(2) strong')!.textContent;

    await userEvent.click(screen.getByRole('button', { name: /Replay source/ }));

    expect(screen.getByLabelText('Saved frame')).toHaveValue('0');
    expect(document.querySelector('.metric-strip > div:nth-child(2) strong')).toHaveTextContent(
      energy!,
    );
  });

  it.each(['frames', 'observables'] as const)(
    'shows the saved %s failure while retaining the other successful result',
    async (failed) => {
      const reason = `Saved ${failed} checksum mismatch`;
      mockEngine({
        runs: [savedRun('a', 'Partial result')],
        ...(failed === 'frames'
          ? { frameList: () => response({ detail: reason }, 500) }
          : { observables: () => response({ detail: reason }, 500) }),
      });
      await ready();
      await userEvent.click(screen.getByRole('button', { name: /Partial result/ }));
      await waitFor(() =>
        expect(
          screen.getAllByRole('alert').some((alert) => alert.textContent?.includes(reason)),
        ).toBe(true),
      );

      if (failed === 'frames') {
        await userEvent.click(screen.getByRole('tab', { name: 'Diagnostics' }));
        expect(screen.getByRole('row', { name: 'norm 1 1 0' })).toBeInTheDocument();
      } else {
        expect(screen.getByLabelText('Saved frame')).toBeInTheDocument();
        await waitFor(() =>
          expect(
            document.querySelector('.metric-strip > div:nth-child(2) strong'),
          ).toHaveTextContent('1 (dimensionless)'),
        );
      }
    },
  );

  it('ignores a late saved-result failure after another run is selected', async () => {
    let finishOldFrames!: (value: Response) => void;
    mockEngine({
      runs: [savedRun('a', 'Older source'), savedRun('b', 'Selected source')],
      frameList: (id) =>
        id === 'a'
          ? new Promise((resolve) => {
              finishOldFrames = resolve;
            })
          : response([{ index: 0, time: 1 }]),
    });
    await ready();
    await userEvent.click(screen.getByRole('button', { name: /Older source/ }));
    await waitFor(() => expect(finishOldFrames).toBeTypeOf('function'));
    await userEvent.click(screen.getByRole('button', { name: /Selected source/ }));
    await waitFor(() => expect(document.querySelector('.plot-caption')).toHaveTextContent('t = 1'));

    await act(async () => {
      finishOldFrames(response({ detail: 'Obsolete frame index is unreadable' }, 500));
    });

    expect(screen.getByRole('heading', { name: 'Selected source' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(document.querySelector('.plot-caption')).toHaveTextContent('t = 1');
  });

  it('recovers polling and clears only its own error while preserving an unrelated comparison failure', async () => {
    const running = { ...savedRun('a', 'Recovering source'), status: 'running' as const };
    let statusReads = 0;
    let finishRecovery!: (value: Response) => void;
    mockEngine({
      runs: [running, savedRun('b', 'Comparison source')],
      status: () => {
        statusReads += 1;
        return statusReads === 1
          ? response({ detail: 'Temporary status service failure' }, 503)
          : new Promise((resolve) => {
              finishRecovery = resolve;
            });
      },
      comparisonB: Promise.resolve(
        response({ detail: 'Comparison measurements are unreadable' }, 500),
      ),
    });
    await ready();
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /Recovering source/ }));
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByRole('alert')).toHaveTextContent('Temporary status service failure');
      fireEvent.click(screen.getByRole('tab', { name: 'Compare' }));
      await act(async () => {
        fireEvent.change(screen.getByLabelText('Comparison run', { exact: true }), {
          target: { value: 'b' },
        });
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(
        screen
          .getAllByRole('alert')
          .some((alert) => alert.textContent?.includes('Comparison measurements are unreadable')),
      ).toBe(true);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
      expect(statusReads).toBe(2);
      await act(async () => {
        finishRecovery(response(savedRun('a', 'Recovering source')));
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(document.querySelector('.run-status')).toHaveTextContent('completed');
      expect(screen.queryByText(/Temporary status service failure/)).not.toBeInTheDocument();
      expect(screen.getByRole('alert')).toHaveTextContent('Comparison measurements are unreadable');
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps a missing-run error visible without repeatedly requesting a permanent 404', async () => {
    let statusReads = 0;
    mockEngine({
      runs: [{ ...savedRun('a', 'Missing source'), status: 'running' }],
      status: () => {
        statusReads += 1;
        return response({ detail: 'Run a no longer exists' }, 404);
      },
    });
    await ready();
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /Missing source/ }));
        await vi.advanceTimersByTimeAsync(5000);
      });

      expect(screen.getByRole('alert')).toHaveTextContent('Run a no longer exists');
      expect(statusReads).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps the authoritative draft rejection visible beside Run when Parameters are hidden', async () => {
    const reason = 'Working memory estimate exceeds max_working_bytes';
    mockEngine({
      resolve: (value) =>
        value.grid.points[0] === 128 ? response({ detail: reason }, 422) : response(value),
    });
    await ready();
    fireEvent.change(screen.getByLabelText('Grid points'), { target: { value: '128' } });
    expect(await screen.findByRole('alert')).toHaveTextContent(reason);
    expect(screen.getAllByRole('alert')).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: 'Toggle parameter panel' }));

    expect(screen.getByRole('button', { name: 'Run simulation' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent(reason);
    expect(screen.getByRole('alert').closest('footer')).toContainElement(
      screen.getByRole('button', { name: 'Run simulation' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Toggle parameter panel' }));
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });
});
