import { useEffect, useRef, useState } from 'react';
import type { Frame, Row, UnitScales, Values, ViewMode } from './types';

const PALETTE = [
  'var(--plot-primary)',
  'var(--plot-reference)',
  'var(--plot-secondary)',
  'var(--plot-tertiary)',
];
const flatten = (v: Values) => v.flat() as number[];
const number = (n: number | null | undefined, digits = 4) =>
  n == null || !Number.isFinite(n)
    ? 'Unavailable'
    : Math.abs(n) > 1e4 || (Math.abs(n) < 0.001 && n !== 0)
      ? n.toExponential(digits - 1)
      : Number(n.toPrecision(digits)).toString();

function extent(a: number[]): [number, number] {
  const finite = a.filter(Number.isFinite);
  if (!finite.length) return [0, 1];
  let min = Math.min(...finite),
    max = Math.max(...finite);
  if (min === max) {
    const padding = Math.max(0.5, Math.abs(min) * 0.05);
    min = Math.max(-Number.MAX_VALUE, min - padding);
    max = Math.min(Number.MAX_VALUE, max + padding);
  }
  return [min, max];
}

function axisTicks([lo, hi]: [number, number], count: number): number[] {
  return [
    ...new Set(
      Array.from({ length: count }, (_, i) => {
        const fraction = i / (count - 1);
        return lo * (1 - fraction) + hi * fraction;
      }),
    ),
  ];
}

function tickLabels(ticks: number[]): string[] {
  const spacing = Math.min(...ticks.slice(1).map((value, i) => value - ticks[i]));
  return ticks.map((value) => {
    const digits = Math.max(
      4,
      Math.min(
        17,
        Math.floor(Math.log10(Math.abs(value) || spacing)) - Math.floor(Math.log10(spacing)) + 2,
      ),
    );
    return number(value, digits);
  });
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

export function LinePlot({
  series,
  xLabel = 'x',
  yLabel = '',
  height = 280,
  fixedDomain,
  fixedRange,
}: {
  series: { x: number[]; y: (number | null)[]; label: string; color?: string; dashed?: boolean }[];
  xLabel?: string;
  yLabel?: string;
  height?: number;
  fixedDomain?: [number, number];
  fixedRange?: [number, number];
}) {
  const { ref, width } = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const top = 25,
    bottom = 43;
  const xRange = fixedDomain ?? extent(series.flatMap((s) => s.x));
  const yRange =
    fixedRange ?? extent(series.flatMap((s) => s.y).filter((y): y is number => y !== null));
  // Scale before subtraction so opposite finite extremes do not overflow the span.
  const padding = fixedRange ? 0 : yRange[1] * 0.08 - yRange[0] * 0.08;
  yRange[0] = Math.max(-Number.MAX_VALUE, yRange[0] - padding);
  yRange[1] = Math.min(Number.MAX_VALUE, yRange[1] + padding);
  const ticks = width < 420 ? 3 : 5;
  const xTicks = axisTicks(xRange, ticks),
    yTicks = axisTicks(yRange, 4);
  const xLabels = tickLabels(xTicks),
    yLabels = tickLabels(yTicks);
  // Reserve room for the 11px measured face, including signs and scientific notation.
  const left = Math.max(64, ...yLabels.map((label) => label.length * 8 + 32)),
    right = Math.max(24, ...xLabels.map((label) => label.length * 4 + 8));
  const xScale = Math.max(...xRange.map(Math.abs)) || 1,
    yScale = Math.max(...yRange.map(Math.abs)) || 1;
  const sx = (x: number) =>
    left +
    ((x / xScale - xRange[0] / xScale) / (xRange[1] / xScale - xRange[0] / xScale)) *
      Math.max(1, width - left - right);
  const sy = (y: number) =>
    height -
    bottom -
    ((y / yScale - yRange[0] / yScale) / (yRange[1] / yScale - yRange[0] / yScale)) *
      (height - top - bottom);
  return (
    <div ref={ref} className="line-plot">
      <svg
        role="img"
        aria-label={`${yLabel || 'Simulation values'} versus ${xLabel}`}
        width="100%"
        height={height}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          const fraction = Math.max(
            0,
            Math.min(1, (e.clientX - box.left - left) / Math.max(1, width - left - right)),
          );
          setHover(xRange[0] * (1 - fraction) + xRange[1] * fraction);
        }}
      >
        {xTicks.map((x, i) => {
          return (
            <g key={`x${x}`}>
              <line className="plot-grid" x1={sx(x)} x2={sx(x)} y1={top} y2={height - bottom} />
              <text className="plot-text" x={sx(x)} y={height - bottom + 19} textAnchor="middle">
                {xLabels[i]}
              </text>
            </g>
          );
        })}
        {yTicks.map((y, i) => {
          return (
            <g key={`y${y}`}>
              <line className="plot-grid" x1={left} x2={width - right} y1={sy(y)} y2={sy(y)} />
              <text className="plot-text" x={left - 10} y={sy(y) + 4} textAnchor="end">
                {yLabels[i]}
              </text>
            </g>
          );
        })}
        <rect
          className="plot-frame"
          x={left}
          y={top}
          width={Math.max(1, width - left - right)}
          height={height - top - bottom}
        />
        {series.map((s, i) => (
          <path
            key={s.label}
            fill="none"
            stroke={s.color ?? PALETTE[i % PALETTE.length]}
            strokeWidth="1.7"
            strokeDasharray={s.dashed ? '5 5' : undefined}
            d={s.y
              .map((y, j) =>
                y !== null && Number.isFinite(y)
                  ? `${j && Number.isFinite(s.y[j - 1]) ? 'L' : 'M'}${sx(s.x[j]).toFixed(2)},${sy(y).toFixed(2)}`
                  : '',
              )
              .join(' ')}
          />
        ))}
        {hover !== null && (
          <line
            x1={sx(hover)}
            x2={sx(hover)}
            y1={top}
            y2={height - bottom}
            className="hover-line"
          />
        )}
        <text className="plot-axis" x={left} y={13}>
          {yLabel}
        </text>
        <text
          className="plot-axis"
          x={(left + width - right) / 2}
          y={height - 5}
          textAnchor="middle"
        >
          {xLabel}
        </text>
      </svg>
      <div className="plot-legend">
        {series.map((s, i) => (
          <span key={s.label}>
            <i style={{ background: s.color ?? PALETTE[i % PALETTE.length] }} />
            {s.label}
            {hover !== null && s.x.length > 0 && (
              <b>
                {number(
                  s.y[
                    s.x.reduce(
                      (best, x, j) =>
                        Math.abs(x - hover) < Math.abs(s.x[best] - hover) ? j : best,
                      0,
                    )
                  ],
                  15,
                )}
              </b>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

function phaseRGB(p: number): [number, number, number] {
  const h = (p / (2 * Math.PI) + 1.5) % 1;
  const f = (n: number) => {
    const k = (n + h * 12) % 12;
    return 255 * (0.58 - 0.4 * Math.max(-1, Math.min(k - 3, 9 - k, 1)));
  };
  return [f(0), f(8), f(4)];
}

function densityRGB(t: number): [number, number, number] {
  const stops = [
    [8, 18, 35],
    [30, 69, 105],
    [24, 133, 144],
    [99, 210, 173],
    [246, 240, 175],
  ];
  const p = Math.max(0, Math.min(1, t)) * (stops.length - 1),
    a = Math.floor(p),
    b = Math.min(a + 1, stops.length - 1),
    f = p - a;
  return stops[a].map((v, i) => v + f * (stops[b][i] - v)) as [number, number, number];
}

export function FieldView({
  frame,
  mode,
  potential,
  physical,
  units,
  slice,
  currentOffset = 0,
  autoscale = false,
}: {
  frame: Frame;
  mode: ViewMode;
  potential: boolean;
  physical: boolean;
  units: UnitScales;
  slice: number;
  currentOffset?: number;
  autoscale?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [position, setPosition] = useState<{ ix: number; iy: number } | null>(null);
  const dimension = frame.dimension;
  const l = physical ? units.length_nm : 1;
  const densityFactor = physical
    ? dimension === 1
      ? units.density_per_nm
      : units.density_per_nm2
    : 1;
  const currentFactor = physical
    ? dimension === 1
      ? units.current_per_fs
      : units.current_per_nm_fs
    : 1;
  const data =
    mode === 'phase' ? frame.phase : mode === 'current' ? (frame.current_x ?? []) : frame.density;
  const factor = mode === 'density' ? densityFactor : mode === 'current' ? currentFactor : 1;
  const values = flatten(data).map((x) => x * factor);
  const peak = Math.max(...flatten(frame.density), 0);
  const densityMax =
    (!autoscale && frame.density_scale_max !== undefined ? frame.density_scale_max : peak) *
    densityFactor;
  const currentMax = Math.max(...values.map(Math.abs), 0);
  // Probability density has a physical zero; generic padding creates fictitious negative density.
  const [min, max] =
    mode === 'density'
      ? [0, densityMax]
      : mode === 'phase'
        ? [-Math.PI, Math.PI]
        : [-currentMax, currentMax];
  const unit =
    mode === 'phase'
      ? 'rad'
      : mode === 'density'
        ? physical
          ? `nm⁻${dimension === 1 ? '¹' : '²'}`
          : '|ψ|²'
        : physical
          ? dimension === 1
            ? 'fs⁻¹'
            : 'nm⁻¹ fs⁻¹'
          : 'jₓ';
  useEffect(() => {
    if (dimension !== 2 || !canvas.current) return;
    const array = data as number[][],
      ny = array.length,
      nx = array[0]?.length ?? 0;
    if (!nx || !ny) return;
    const ctx = canvas.current.getContext('2d');
    if (!ctx) return;
    canvas.current.width = nx;
    canvas.current.height = ny;
    const img = ctx.createImageData(nx, ny);
    const potentials = frame.potential as number[][];
    const pmax = Math.max(...flatten(frame.potential).map(Math.abs), 1e-30);
    for (let row = 0; row < ny; row++)
      for (let col = 0; col < nx; col++) {
        const j = ny - 1 - row,
          v = array[j][col] * factor;
        let color: [number, number, number];
        if (mode === 'phase') {
          color = phaseRGB(v);
          const alpha =
            peak > 0 ? Math.min(1, Math.sqrt((frame.density as number[][])[j][col] / peak) * 2) : 0;
          color = color.map((c) => 10 + (c - 10) * alpha) as [number, number, number];
        } else if (mode === 'current') {
          const t = Math.min(1, Math.abs(v) / Math.max(Math.abs(min), Math.abs(max), 1e-30));
          color =
            v >= 0
              ? [15 + 65 * t, 25 + 190 * t, 45 + 155 * t]
              : [15 + 210 * t, 25 + 73 * t, 45 + 90 * t];
        } else color = densityRGB(v / (max || 1));
        if (potential && Math.abs(potentials?.[j]?.[col] ?? 0) / pmax > 0.2) {
          const edge = 0.25;
          color = color.map((c, k) => c * (1 - edge) + [215, 196, 150][k] * edge) as [
            number,
            number,
            number,
          ];
        }
        const i = (row * nx + col) * 4;
        img.data[i] = color[0];
        img.data[i + 1] = color[1];
        img.data[i + 2] = color[2];
        img.data[i + 3] = 255;
      }
    ctx.putImageData(img, 0, 0);
  }, [frame, mode, potential, factor, data, dimension, max, min, peak]);

  if (mode === 'current' && !frame.current_x)
    return (
      <div className="tab-empty">
        <h3>Current is unavailable in this frame.</h3>
        <p>Load a frame saved with current diagnostics.</p>
      </div>
    );
  if (mode === 'phase' && (peak === 0 || frame.validity?.conditional_status === 'numerically_zero'))
    return (
      <div className="tab-empty">
        <h3>Phase is unavailable: no probability survives.</h3>
        <p>The argument of the zero wavefunction is undefined.</p>
      </div>
    );
  if (dimension === 1) {
    const y =
        mode === 'phase'
          ? values.map((v, i) => ((frame.density as number[])[i] / peak > 1e-8 ? v : NaN))
          : values,
      x = frame.axes.x.map((x) => (x + (mode === 'current' ? currentOffset : 0)) * l);
    const ps = flatten(frame.potential);
    const pmin = Math.min(...ps),
      pmax = Math.max(...ps);
    // Overlay height expresses potential shape only, within the field's own physical range.
    const overlay = ps.map((p) =>
      pmax === pmin
        ? Math.max(min, Math.min(max, 0))
        : min + ((p - pmin) / (pmax - pmin)) * (max - min) * 0.8,
    );
    return (
      <LinePlot
        height={345}
        xLabel={`x ${physical ? '(nm)' : '(dimensionless)'}`}
        yLabel={`${mode === 'current' ? 'Signed current' : mode === 'phase' ? 'Phase' : 'Probability density'} (${unit})`}
        fixedRange={[min, max > min ? max : min + 1]}
        series={[
          { x, y, label: mode === 'current' ? 'jₓ' : mode === 'phase' ? 'arg ψ' : '|ψ|²' },
          ...(potential
            ? [
                {
                  x: frame.axes.x.map((v) => v * l),
                  y: overlay,
                  label: 'Potential (scaled)',
                  color: 'var(--plot-reference)',
                  dashed: true,
                },
              ]
            : []),
        ]}
      />
    );
  }
  const xs = frame.axes.x.map((x) => x + (mode === 'current' ? currentOffset : 0)),
    ys = frame.axes.y ?? [],
    ratio = (xs[xs.length - 1] - xs[0]) / (ys[ys.length - 1] - ys[0] || 1);
  const hovered =
    position && position.ix < xs.length && position.iy < ys.length
      ? {
          x: xs[position.ix] * l,
          y: ys[position.iy] * l,
          value: (data as number[][])[position.iy]?.[position.ix] * factor,
        }
      : null;
  return (
    <div className="field-2d">
      <div className="heatmap-scale">
        <span>{unit}</span>
        <div
          className={
            mode === 'phase'
              ? 'phase-gradient'
              : mode === 'current'
                ? 'current-gradient'
                : 'density-gradient'
          }
        />
        <span>{number(mode === 'phase' ? Math.PI : max)}</span>
        <span>{number(mode === 'phase' ? -Math.PI : min)}</span>
      </div>
      <div className="heatmap-outer">
        <span className="map-y-max">{number((ys[ys.length - 1] ?? 0) * l)}</span>
        <span className="map-y-min">{number((ys[0] ?? 0) * l)}</span>
        <span className="map-y-label">y {physical ? '(nm)' : '(dim.)'}</span>
        <div className="heatmap-image">
          <canvas
            ref={canvas}
            className="heatmap"
            role="img"
            aria-label={`Two-dimensional ${mode} field, x increasing right and y increasing upward`}
            style={{ aspectRatio: ratio, width: Math.min(650, 320 * ratio) }}
            onMouseLeave={() => setPosition(null)}
            onMouseMove={(e) => {
              const b = e.currentTarget.getBoundingClientRect();
              const ix = Math.min(
                xs.length - 1,
                Math.max(0, Math.floor(((e.clientX - b.left) / b.width) * xs.length)),
              );
              const iy = Math.min(
                ys.length - 1,
                Math.max(0, Math.floor((1 - (e.clientY - b.top) / b.height) * ys.length)),
              );
              setPosition({ ix, iy });
            }}
          />
          {slice >= 0 && (
            <div
              className="slice-line"
              style={{ top: `${100 * (1 - slice / Math.max(1, ys.length - 1))}%` }}
            />
          )}
          {frame.screen && (
            <div
              className="screen-line"
              style={{ left: `${(100 * (frame.screen.x - xs[0])) / (xs[xs.length - 1] - xs[0])}%` }}
            />
          )}
        </div>
        <div className="map-x-axis">
          <span>{number(xs[0] * l)}</span>
          <span>x {physical ? '(nm)' : '(dim.)'}</span>
          <span>{number(xs[xs.length - 1] * l)}</span>
        </div>
      </div>
      <div className="field-readout">
        {hovered
          ? `x ${number(hovered.x)}  ·  y ${number(hovered.y)}  ·  ${number(hovered.value)} ${unit}`
          : 'Move over the field to inspect coordinates and amplitude'}
      </div>
    </div>
  );
}

export function SlicePlot({
  frame,
  index,
  units,
  physical,
  autoscale = false,
}: {
  frame: Frame;
  index: number;
  units: UnitScales;
  physical: boolean;
  autoscale?: boolean;
}) {
  const density = frame.density as number[][];
  const row = density[Math.max(0, Math.min(index, density.length - 1))];
  if (!row) return null;
  const scale =
    (autoscale ? Math.max(...density.flat()) : frame.density_scale_max) *
    (physical ? units.density_per_nm2 : 1);
  return (
    <LinePlot
      fixedRange={[0, scale || 1]}
      height={180}
      xLabel={physical ? 'x (nm)' : 'x'}
      yLabel={`Density slice at y = ${number((frame.axes.y?.[index] ?? 0) * (physical ? units.length_nm : 1))}`}
      series={[
        {
          x: frame.axes.x.map((x) => x * (physical ? units.length_nm : 1)),
          y: row.map((x) => x * (physical ? units.density_per_nm2 : 1)),
          label: 'Horizontal slice',
        },
      ]}
    />
  );
}

export function DiagnosticPlot({
  rows,
  physical,
  units,
  selected,
}: {
  rows: Row[];
  physical: boolean;
  units: UnitScales;
  selected: string;
}) {
  const time = (r: Row) => (r.time ?? r.t ?? 0) * (physical ? units.time_fs : 1);
  const series = [
    {
      x: rows.map(time),
      y: rows.map((r) => r[selected] ?? null),
      label: selected.replaceAll('_', ' '),
    },
  ];
  return (
    <LinePlot
      height={240}
      xLabel={physical ? 'Time (fs)' : 'Time (dimensionless)'}
      yLabel={selected.replaceAll('_', ' ')}
      series={series}
    />
  );
}
