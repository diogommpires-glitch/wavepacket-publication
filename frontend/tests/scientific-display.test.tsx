import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DiagnosticPlot, FieldView, LinePlot } from '../src/plots';
import { field2d, testUnits } from './fixtures';
import { canvasFrames } from './setup';

describe('scientific field rendering', () => {
  it.each([
    [1e20, 1e20],
    [Number.MAX_VALUE, Number.MAX_VALUE],
    [-Number.MAX_VALUE, -Number.MAX_VALUE],
    [-Number.MAX_VALUE, Number.MAX_VALUE],
  ])('keeps finite plotted readings inside the chart for %s and %s', (a, b) => {
    const { container } = render(
      <LinePlot series={[{ x: [0, 1], y: [a, b], label: 'Finite readings' }]} />,
    );
    const path = container.querySelector('path[fill="none"]')!.getAttribute('d')!;
    expect(path).not.toMatch(/NaN|Infinity/);
    const coordinates = [...path.matchAll(/[ML]([\d.-]+),([\d.-]+)/g)].map((match) => [
      Number(match[1]),
      Number(match[2]),
    ]);
    expect(coordinates).toHaveLength(2);
    const chart = container.querySelector('.plot-frame')!;
    const left = Number(chart.getAttribute('x'));
    const right = left + Number(chart.getAttribute('width'));
    const top = Number(chart.getAttribute('y'));
    const bottom = top + Number(chart.getAttribute('height'));
    for (const [x, y] of coordinates) {
      expect(x).toBeGreaterThanOrEqual(left - 0.01);
      expect(x).toBeLessThanOrEqual(right + 0.01);
      expect(y).toBeGreaterThanOrEqual(top - 0.01);
      expect(y).toBeLessThanOrEqual(bottom + 0.01);
    }
  });

  it('retains norm-scale variation in axis labels and inspected values', () => {
    const { container } = render(
      <DiagnosticPlot
        rows={[
          { time: 0, norm: 1 - 1e-8 },
          { time: 1, norm: 1 + 1e-8 },
        ]}
        physical={false}
        units={testUnits()}
        selected="norm"
      />,
    );
    const ticks = [...container.querySelectorAll('text[text-anchor="end"]')].map(
      (node) => node.textContent!,
    );
    expect(new Set(ticks).size).toBe(4);
    expect(Number(ticks[0])).toBeLessThan(1);
    expect(Number(ticks.at(-1))).toBeGreaterThan(1);
    fireEvent.mouseMove(container.querySelector('svg')!, { clientX: 590 });
    expect(Number(container.querySelector('.plot-legend b')!.textContent)).toBeCloseTo(
      1 + 1e-8,
      12,
    );
  });

  it('renders zero density as zero colour with a nonnegative scale', () => {
    const { container } = render(
      <FieldView
        frame={field2d([
          [0, 0],
          [0, 0],
        ])}
        mode="density"
        potential={false}
        physical={false}
        units={testUnits()}
        slice={-1}
      />,
    );
    expect([...canvasFrames.at(-1)!.data.slice(0, 4)]).toEqual([8, 18, 35, 255]);
    const labels = [...container.querySelectorAll('.heatmap-scale > span')].map(
      (node) => node.textContent,
    );
    expect(labels).not.toContain('-0.5');
    expect(labels.at(-1)).toBe('0');
  });

  it('uses zero as the lower bound for a uniform positive density', () => {
    const { container } = render(
      <FieldView
        frame={field2d([
          [0.2, 0.2],
          [0.2, 0.2],
        ])}
        mode="density"
        potential={false}
        physical={false}
        units={testUnits()}
        slice={-1}
      />,
    );
    const labels = [...container.querySelectorAll('.heatmap-scale > span')].map(
      (node) => node.textContent,
    );
    expect(labels.at(-1)).toBe('0');
    expect(labels.at(-2)).toBe('0.2');
  });

  it('marks phase unavailable when no probability survives', () => {
    render(
      <FieldView
        frame={field2d([
          [0, 0],
          [0, 0],
        ])}
        mode="phase"
        potential={false}
        physical={false}
        units={testUnits()}
        slice={-1}
      />,
    );
    expect(screen.getByText(/phase is unavailable/i)).toBeInTheDocument();
  });

  it('keeps unavailable conditional measurements as gaps rather than zeros', () => {
    const rows = [
      { time: 0, energy: 1 },
      { time: 1, energy: null },
      { time: 2, energy: 2 },
    ];
    const { container } = render(
      <DiagnosticPlot rows={rows} physical={false} units={testUnits()} selected="energy" />,
    );
    const path = container.querySelector('path[fill="none"]')!;
    expect((path.getAttribute('d')!.match(/M/g) ?? []).length).toBe(2);
  });

  it('preserves density decay against the saved-frame maximum, with explicit autoscaling opt-in', () => {
    const saved = {
      ...field2d([
        [0.1, 0.1],
        [0.1, 0.1],
      ]),
      density_scale_max: 1,
    };
    const { container, rerender } = render(
      <FieldView
        frame={saved}
        mode="density"
        potential={false}
        physical={true}
        units={testUnits(2)}
        slice={-1}
      />,
    );
    expect(container.querySelector('.heatmap-scale > span:nth-last-child(2)')).toHaveTextContent(
      '0.25',
    );
    const fixedPixel = [...canvasFrames.at(-1)!.data.slice(0, 3)];
    rerender(
      <FieldView
        frame={saved}
        mode="density"
        potential={false}
        physical={true}
        units={testUnits(2)}
        slice={-1}
        autoscale
      />,
    );
    expect(container.querySelector('.heatmap-scale > span:nth-last-child(2)')).toHaveTextContent(
      '0.025',
    );
    expect([...canvasFrames.at(-1)!.data.slice(0, 3)]).not.toEqual(fixedPixel);
  });

  it('uses a symmetric signed-current colour scale with the physical current dimension', () => {
    const current = {
      ...field2d([
        [1, 1],
        [1, 1],
      ]),
      current_x: [
        [-1, 0.2],
        [0, 0.5],
      ],
    };
    const { container } = render(
      <FieldView
        frame={current}
        mode="current"
        potential={false}
        physical={true}
        units={{ ...testUnits(2), time_fs: 5, current_per_fs: 0.2, current_per_nm_fs: 0.1 }}
        slice={-1}
      />,
    );
    const labels = [...container.querySelectorAll('.heatmap-scale > span')].map(
      (node) => node.textContent,
    );
    expect(labels).toEqual(['nm⁻¹ fs⁻¹', '0.1', '-0.1']);
  });
});
