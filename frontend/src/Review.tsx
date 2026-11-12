import { RotateCcw, Terminal } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import type { Config, Preset, ValidationReport } from './types';
import { api, displayName } from './types';

const limits = (preset?: Preset | null) =>
  typeof preset?.limitations === 'string' ? [preset.limitations] : (preset?.limitations ?? []);
function ValidationEvidence() {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [error, setError] = useState('');
  const refresh = useCallback(() => {
    api<ValidationReport>('/validation?suite=full')
      .then((value) => {
        setReport(value);
        setError('');
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  return (
    <div className="validation-evidence">
      <div className="section-line">
        <div>
          <h3>Saved scientific validation</h3>
          <p>Actual recorded checks, separate from this experiment’s evidence route.</p>
        </div>
        <button type="button" className="secondary-button" onClick={refresh}>
          <RotateCcw size={13} />
          Refresh
        </button>
      </div>
      {error && <p className="field-note">Validation report unavailable: {error}</p>}
      {report?.summary ? (
        <>
          <p
            className={`validation-summary ${report.freshness?.source_match ? report.status : 'stale'}`}
          >
            <span>
              {report.summary.passed} / {report.summary.total} checks passed
            </span>
            <span>
              {report.suite} suite,{' '}
              {report.created_utc ? new Date(report.created_utc).toLocaleString() : ''}
            </span>
          </p>
          <p className="field-note">
            Source match:{' '}
            {report.freshness?.source_match === true
              ? 'current sources match the saved report'
              : report.freshness?.source_match === false
                ? 'stale: source files changed; rerun the suite'
                : 'unverified: no source fingerprint available'}
            .
          </p>
          {report.freshness && (
            <details>
              <summary>Validation provenance</summary>
              <pre>{JSON.stringify(report.freshness, null, 2)}</pre>
            </details>
          )}
          <div className="validation-cases">
            {report.cases?.map((item) => (
              <details key={item.id}>
                <summary>
                  <span>{displayName(item.id)}</span>
                  <small>{item.status}</small>
                </summary>
                <div>
                  <p>{item.evidence}</p>
                  <pre>
                    {JSON.stringify(
                      { metrics: item.metrics, criteria: item.criteria, notes: item.notes },
                      null,
                      2,
                    )}
                  </pre>
                </div>
              </details>
            ))}
          </div>
          {report.limitations?.map((item) => (
            <p className="field-note" key={item}>
              {item}
            </p>
          ))}
        </>
      ) : (
        <p className="field-note">
          {report?.note ?? 'No saved validation report has been loaded.'} Execute the validation
          suite from the CLI, then refresh this panel.
        </p>
      )}
    </div>
  );
}

export default function Review({ config, preset }: { config: Config; preset?: Preset | null }) {
  const evidence = preset?.evidence_record;
  const exactPreset = !!preset && JSON.stringify(config) === JSON.stringify(preset.config);
  const evidenceStatus = exactPreset
    ? (evidence?.status ?? 'report_required')
    : 'edited_unverified';
  return (
    <div className="review-content">
      <h2>Read the simulation, not just the picture.</h2>
      <p className="review-intro">
        This laboratory evolves a single-particle wavefunction under a static potential. Its
        numerical model, approximations, and validation are part of every saved result. Review the
        physics, implementation and evidence below.
      </p>
      <div className="equation-panel">
        <div>i ∂ψ/∂t = [−½∇² + V − iW] ψ</div>
        <span>Dimensionless Schrödinger equation</span>
        <p>
          ℏ = m = 1, complex128, {config.grid.points.length} spatial dimension
          {config.grid.points.length === 1 ? '' : 's'},{' '}
          {config.boundary.kind === 'cap'
            ? 'absorbing open-domain approximation'
            : 'periodic closed domain'}
        </p>
      </div>
      <div className="review-grid">
        <article>
          <h3>Which Hamiltonian?</h3>
          <p>
            Fourier spectral and second-order finite differences approximate kinetic energy
            differently. Compare integrators on a matched discrete Hamiltonian; study spatial error
            separately.
          </p>
          <code>T(k) = k²/2</code>
          <code>Tₕ(k) = 2 sin²(kΔx/2)/Δx²</code>
          <p className="review-question">
            Review: does each compared run use the same grid, potential, and kinetic operator?
          </p>
        </article>
        <article>
          <h3>What does the step do?</h3>
          <p>
            Strang applies half a potential step, a kinetic step in Fourier space, then the
            remaining potential step. Yoshida composes symmetric Strang steps for fourth-order
            temporal accuracy on closed systems.
          </p>
          <code>S₂(h) = exp(−iVh/2) exp(−iTh) exp(−iVh/2)</code>
          <p>
            Crank-Nicolson solves a reusable sparse FD2 system in one dimension. Its preserved norm
            does not eliminate phase error.
          </p>
        </article>
        <article>
          <h3>What constitutes evidence?</h3>
          <p>
            Analytical free packets and oscillator solutions test the physical approximation.
            Independently assembled small-H matrix exponentials isolate propagation error. Grid,
            timestep, and domain refinement answer different questions.
          </p>
          <p className="review-question">
            Review: could the method conserve probability while producing the wrong dynamics?
          </p>
        </article>
        <article>
          <h3>What do boundaries change?</h3>
          <p>
            FFT evolution is periodic. A complex absorbing layer deliberately reduces norm;
            remaining plus absorbed probability is an accounting test, while absorber reflection
            requires a separate study.
          </p>
          <p>
            Screen current is a signed diagnostic. A density slice or clipped current is not a
            general detector-count distribution.
          </p>
        </article>
      </div>
      <div className="review-experiment">
        <h3>{preset?.name ?? config.name}</h3>
        <p>{preset?.question ?? 'Use the saved configuration to state the physical question.'}</p>
        <ul>
          {limits(preset).map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </div>
      <section className="preset-evidence" aria-label="Exact configuration evidence">
        <h3>Exact configuration evidence</h3>
        <p>
          Status: <strong>{displayName(evidenceStatus)}</strong>.{' '}
          {evidence?.scope ??
            'A validation route describes a method; it does not certify an arbitrary configuration.'}
        </p>
        {evidence && (
          <details>
            <summary>Preset hash, checked conditions, and measured evidence</summary>
            <p>
              Preset configuration SHA-256: <code>{evidence.configuration_sha256}</code>
            </p>
            {!exactPreset && (
              <p>The current draft differs from this preset hash and requires fresh checks.</p>
            )}
            <pre>
              {JSON.stringify(
                {
                  check_ids: evidence.check_ids,
                  conditions: evidence.conditions,
                  measured_conditions: evidence.measured_conditions,
                  metrics: evidence.metrics,
                  report_sha256: evidence.report_sha256,
                  reference_configuration_sha256: evidence.reference_configuration_sha256,
                },
                null,
                2,
              )}
            </pre>
          </details>
        )}
      </section>
      <div className="reproduce-strip">
        <Terminal size={18} />
        <div>
          <strong>Reproduce this experiment</strong>
          <code>wavepacket experiment {preset?.id ?? 'EXPERIMENT_ID'}</code>
          <code>wavepacket validate --suite full</code>
        </div>
      </div>
      <ValidationEvidence />
      <p className="field-note">
        Full derivations, executable notebooks, and code-review exercises are included in the
        project documentation. Preset evidence labels describe the validation route, not a guarantee
        for arbitrary edited parameters.
      </p>
    </div>
  );
}
