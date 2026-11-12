import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import ConfigPanel from '../src/ConfigPanel';
import { FieldView } from '../src/plots';
import { config, field2d, testUnits } from './fixtures';

it('binds a stationary-pointer readout to the current field, saved frame, and physical units', () => {
  const saved = {
    ...field2d([
      [0.2, 0.4],
      [0.1, 0.3],
    ]),
    phase: [
      [1.25, 1.25],
      [1.25, 1.25],
    ],
    current_x: [
      [1, 1],
      [1, 1],
    ],
  };
  const props = {
    frame: saved,
    mode: 'density' as const,
    physical: false,
    potential: false,
    units: testUnits(),
    slice: -1,
  };
  const { container, rerender } = render(<FieldView {...props} />);
  const canvas = screen.getByRole('img');
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    top: 0,
    width: 100,
    height: 100,
  } as DOMRect);
  fireEvent.mouseMove(canvas, { clientX: 75, clientY: 25 });
  const readout = () => container.querySelector('.field-readout')!;
  expect(readout()).toHaveTextContent('0.3 |ψ|²');

  rerender(<FieldView {...props} mode="phase" />);
  expect(readout()).toHaveTextContent('1.25 rad');

  const later = {
    ...saved,
    phase: [
      [2.5, 2.5],
      [2.5, 2.5],
    ],
  };
  rerender(<FieldView {...props} frame={later} mode="phase" />);
  expect(readout()).toHaveTextContent('2.5 rad');

  rerender(<FieldView {...props} frame={later} mode="current" physical units={testUnits(2)} />);
  expect(readout()).toHaveTextContent('x 2');
  expect(readout()).toHaveTextContent('y 2');
  expect(readout()).toHaveTextContent('0.025 nm⁻¹ fs⁻¹');
});

it('keeps pending physical-unit inputs disabled while a run owns the parameters', () => {
  render(
    <ConfigPanel
      config={{ ...config, units: { mode: 'electron', length_nm: 1 } }}
      onChange={vi.fn()}
      units={null}
      disabled
      errors={[]}
      checking
    />,
  );
  expect(screen.getByLabelText('Unit system')).toBeDisabled();
  expect(screen.getByLabelText(/^Reference length/)).toBeDisabled();
});
