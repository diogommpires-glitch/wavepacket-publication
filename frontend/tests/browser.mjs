import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const base = process.env.WAVEPACKET_URL ?? 'http://127.0.0.1:8765';
const artifacts = new URL('./artifacts/', import.meta.url);
await mkdir(artifacts, { recursive: true });
const selectedBrowser =
  process.env.WAVEPACKET_BROWSER ?? (process.platform === 'win32' ? 'chrome' : 'chromium');
const browser = await chromium.launch({
  channel: selectedBrowser === 'chromium' ? undefined : selectedBrowser,
  headless: true,
});
const page = await browser.newPage({
  viewport: { width: 1536, height: 1000 },
  acceptDownloads: true,
});
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('response', async (response) => {
  if (
    response.url().endsWith('/api/runs') &&
    response.request().method() === 'POST' &&
    response.status() >= 400
  )
    console.log(`RUN START REJECTED ${response.status()} ${await response.text()}`);
});
const results = [];
const check = async (name, fn) => {
  await fn();
  results.push({ name, passed: true });
  console.log(`PASS ${name}`);
};
const waitComplete = async () => {
  await page.locator('.run-status.completed').waitFor({ timeout: 120000 });
  await page.getByLabel('Saved frame', { exact: true }).waitFor();
};

try {
  await page.goto(base, { waitUntil: 'networkidle' });
  await check('sixteen real experiments and connected numerical engine', async () => {
    await page.locator('.experiment-item').nth(15).waitFor();
    assert.equal(await page.locator('.experiment-item').count(), 16);
    assert.equal(await page.locator('.connection.online').count(), 1);
    await page.screenshot({
      path: fileURLToPath(new URL('desktop-ready.png', artifacts)),
      fullPage: true,
    });
  });
  await check('theme toggle persists preference', async () => {
    await page.getByLabel('Switch to light mode').click();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
    await page.getByLabel('Switch to dark mode').click();
  });
  await check('electron-unit inputs roundtrip without changing core settings', async () => {
    const dt = await page.getByLabel(/^Timestep/).inputValue();
    await page.getByLabel('Unit system').selectOption('electron');
    await page.waitForTimeout(250);
    assert(Number(await page.getByLabel(/^Timestep/).inputValue()) > Number(dt));
    await page.getByLabel('Unit system').selectOption('dimensionless');
    assert(Math.abs(Number(await page.getByLabel(/^Timestep/).inputValue()) - Number(dt)) < 1e-9);
  });
  await check(
    'canonical draft rejection blocks admission and preserves editable input',
    async () => {
      const timestep = page.getByLabel(/^Timestep/);
      const initial = await timestep.inputValue();
      await timestep.fill('-1');
      await page.locator('.config-errors[role="alert"]').waitFor();
      assert.equal(await timestep.inputValue(), '-1');
      assert(await page.getByRole('button', { name: 'Run simulation', exact: true }).isDisabled());
      await timestep.fill(initial);
      await page.getByRole('button', { name: 'Run simulation', exact: true }).waitFor();
      assert(await page.getByRole('button', { name: 'Run simulation', exact: true }).isEnabled());
    },
  );
  await check('1D real run, saved frames and diagnostics', async () => {
    await page.getByLabel(/^Duration/).fill('0.1');
    await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
    await waitComplete();
    assert.equal(await page.locator('.field-stage svg').count(), 1);
    await page.getByRole('tab', { name: 'Diagnostics', exact: true }).click();
    await page.locator('tbody tr').first().waitFor();
    assert((await page.locator('tbody tr').count()) >= 8);
    await page.getByRole('tab', { name: 'Wavefunction', exact: true }).click();
    await page.getByLabel('Saved frame', { exact: true }).focus();
    await page.getByLabel('Saved frame', { exact: true }).press('Home');
    await page.getByRole('button', { name: 'arg ψ Phase', exact: true }).click();
    await page.getByRole('button', { name: 'jₓ Current', exact: true }).click();
    await page.getByText(/Shared density scale: maximum across saved frames/).waitFor();
  });
  await check('saved results retain their physical scale when the next draft changes', async () => {
    await page.getByLabel('Result display units', { exact: true }).selectOption('electron');
    const energy = await page.locator('.metric-strip > div:nth-child(2) strong').textContent();
    await page.getByLabel('Unit system', { exact: true }).selectOption('electron');
    await page.getByLabel(/^Reference length/).fill('2');
    assert.equal(
      await page.locator('.metric-strip > div:nth-child(2) strong').textContent(),
      energy,
    );
    await page.getByLabel(/^Reference length/).fill('1');
    await page.getByLabel('Unit system', { exact: true }).selectOption('dimensionless');
    await page.getByLabel('Result display units', { exact: true }).selectOption('dimensionless');
  });
  await check('scientific explanation and configuration download', async () => {
    await page.getByRole('tab', { name: 'Review & theory', exact: true }).click();
    await page
      .getByRole('heading', { name: 'Read the simulation, not just the picture.' })
      .waitFor();
    await page.getByRole('heading', { name: 'Saved scientific validation', exact: true }).waitFor();
    await page.getByRole('button', { name: /^Export/ }).click();
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Configuration JSON', exact: true }).click();
    const downloaded = await downloading;
    assert(downloaded.suggestedFilename().endsWith('.json'));
    await page.getByRole('tab', { name: 'Wavefunction', exact: true }).click();
  });
  await check('2D run, field orientation, slice and replay', async () => {
    await page.getByRole('button', { name: '2D', exact: true }).click();
    await page.locator('.experiment-item').first().click();
    await page.getByLabel(/^Duration/).fill('0.04');
    await page.getByText('Measurements & saved data', { exact: true }).click();
    await page.getByLabel('Record a screen profile', { exact: true }).check();
    await page.getByLabel(/^Screen position x/).fill('-6');
    await page.getByRole('button', { name: '|ψ|² Density', exact: true }).click();
    await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
    await waitComplete();
    await page.locator('canvas.heatmap').waitFor();
    assert(await page.locator('canvas.heatmap').evaluate((c) => c.width > 0 && c.height > 0));
    await page.getByRole('region', { name: 'Screen diagnostics', exact: true }).waitFor();
    assert.equal(await page.locator('.screen-plots svg').count(), 2);
    await page.getByLabel('Show slice', { exact: true }).check();
    await page.getByLabel('Slice y index', { exact: true }).focus();
    await page.getByLabel('Slice y index', { exact: true }).press('Home');
    await page.getByLabel('Slice y index', { exact: true }).press('ArrowRight');
    await page.getByLabel('Saved frame', { exact: true }).focus();
    await page.getByLabel('Saved frame', { exact: true }).press('Home');
    await page.getByLabel('Play replay', { exact: true }).click();
    await page.waitForTimeout(450);
    await page.screenshot({
      path: fileURLToPath(new URL('desktop-2d.png', artifacts)),
      fullPage: true,
    });
  });
  await check('mobile history and replay controls have usable touch targets', async () => {
    const previousViewport = page.viewportSize();
    const names = [
      'Refresh run history',
      'First saved frame',
      'Previous saved frame',
      'Play replay',
      'Next saved frame',
      'Last saved frame',
    ];
    const pause = page.getByLabel('Pause replay', { exact: true });
    if ((await pause.count()) > 0) await pause.click();
    for (const width of [320, 375]) {
      await page.setViewportSize({ width, height: 844 });
      for (const name of names) {
        const control = page.getByLabel(name, { exact: true });
        await control.scrollIntoViewIfNeeded();
        const box = await control.boundingBox();
        assert(
          box && box.width >= 44 && box.height >= 44,
          `${name} has a small touch target at ${width}px`,
        );
        const receivesPointer = await control.evaluate((button) => {
          const rect = button.getBoundingClientRect();
          const points = [
            [rect.left + 2, rect.top + 2],
            [rect.right - 2, rect.top + 2],
            [rect.left + 2, rect.bottom - 2],
            [rect.right - 2, rect.bottom - 2],
            [rect.x + rect.width / 2, rect.y + rect.height / 2],
          ];
          return points.every(([x, y]) => button.contains(document.elementFromPoint(x, y)));
        });
        assert(receivesPointer, `${name} is obscured at ${width}px`);
      }
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      assert(overflow <= 1, `horizontal overflow at ${width}px: ${overflow}px`);
      const first = page.getByLabel('First saved frame', { exact: true });
      if (await first.isEnabled()) await first.click();
      await page.getByLabel('Next saved frame', { exact: true }).click();
      assert.equal(await page.getByLabel('Saved frame', { exact: true }).inputValue(), '1');
      await page.getByLabel('Previous saved frame', { exact: true }).click();
      assert.equal(await page.getByLabel('Saved frame', { exact: true }).inputValue(), '0');
    }
    assert(previousViewport);
    await page.setViewportSize(previousViewport);
  });
  await check('scientific plot labels remain inside their SVG bounds', async () => {
    const plots = page.locator('.line-plot svg:visible');
    assert((await plots.count()) >= 3, 'Expected the density slice and both screen plots');
    const clipped = await plots.evaluateAll((elements) =>
      elements.flatMap((svg) => {
        const bounds = svg.getBoundingClientRect();
        return [...svg.querySelectorAll('text')].flatMap((label) => {
          const text = label.getBoundingClientRect();
          return text.left < bounds.left - 1 ||
            text.right > bounds.right + 1 ||
            text.top < bounds.top - 1 ||
            text.bottom > bounds.bottom + 1
            ? [{ plot: svg.getAttribute('aria-label'), text: label.textContent }]
            : [];
        });
      }),
    );
    assert.deepEqual(clipped, [], `Clipped scientific labels: ${JSON.stringify(clipped)}`);
  });
  await check('saved-run comparison exposes methods', async () => {
    await page.getByRole('tab', { name: 'Compare', exact: true }).click();
    const selector = page.getByLabel('Comparison run', { exact: true });
    const value = await selector.locator('option').nth(1).getAttribute('value');
    assert(value);
    await selector.selectOption(value);
    await page.locator('.comparison-cards article').nth(1).waitFor();
    await page.locator('.comparison-warning').waitFor();
  });
  await check('cooperative cancellation and readable partial run', async () => {
    await page.getByRole('tab', { name: 'Wavefunction', exact: true }).click();
    await page.getByLabel(/^Duration/).fill('100');
    await page.getByLabel(/^Timestep/).fill('0.001');
    await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
    await page.getByRole('button', { name: 'Cancel run', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Cancel run', exact: true }).click();
    await page.locator('.run-status.cancelled').waitFor({ timeout: 30000 });
  });
  await check(
    'configuration imports use canonical defaults and recover from invalid nested values',
    async () => {
      const catalogue = await (await page.request.get(`${base}/api/presets`)).json();
      const invalid = structuredClone(catalogue[0].config);
      invalid.state.center = null;
      const heading = await page.locator('h1').textContent();
      await page.locator('input[type="file"]').setInputFiles({
        name: 'invalid.json',
        mimeType: 'application/json',
        buffer: Buffer.from(JSON.stringify(invalid)),
      });
      await page.getByRole('alert').filter({ hasText: 'Configuration import failed' }).waitFor();
      assert.equal(await page.locator('h1').textContent(), heading);
      const partial = structuredClone(catalogue[0].config);
      delete partial.state.center;
      await page.locator('input[type="file"]').setInputFiles({
        name: 'partial.json',
        mimeType: 'application/json',
        buffer: Buffer.from(JSON.stringify(partial)),
      });
      await page.getByRole('heading', { name: partial.name, exact: true }).waitFor();
      assert.equal(await page.getByRole('alert').count(), 0);
      assert.equal(await page.locator('.application').count(), 1);
    },
  );
  await check('mobile layout stays within viewport', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(250);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    assert(overflow <= 1, `horizontal overflow: ${overflow}px`);
    await page.screenshot({
      path: fileURLToPath(new URL('mobile.png', artifacts)),
      fullPage: true,
    });
  });
  await check('mobile run controls stay visible while editing parameters', async () => {
    const runButton = page.getByRole('button', { name: 'Run simulation', exact: true });
    await runButton.waitFor();
    await page.waitForFunction(() => {
      const button = document.querySelector('.run-actions .primary-button');
      return button instanceof HTMLButtonElement && !button.disabled;
    });
    const timestep = page.getByLabel(/^Timestep/);
    await timestep.focus();
    await timestep.evaluate((input) => input.scrollIntoView({ block: 'center' }));
    const button = await runButton.boundingBox();
    const input = await timestep.boundingBox();
    const dock = await page.locator('.run-bar').boundingBox();
    const viewport = page.viewportSize();
    assert(button && input && dock && viewport, 'Expected measurable mobile controls');
    assert(
      button.y >= 0 && button.y + button.height <= viewport.height,
      'Run action left viewport',
    );
    assert(input.y >= 0 && input.y + input.height <= dock.y, 'Run dock obscures the focused input');
  });
  await check('no uncaught browser errors', async () => assert.deepEqual(errors, []));
  await writeFile(
    new URL('browser-results.json', artifacts),
    JSON.stringify({ base, results, errors }, null, 2),
  );
} catch (error) {
  await page.screenshot({
    path: fileURLToPath(new URL('failure.png', artifacts)),
    fullPage: true,
  });
  console.error(
    'VISIBLE ERROR:',
    await page.locator('.error-banner,.config-errors').allTextContents(),
  );
  await writeFile(
    new URL('browser-results.json', artifacts),
    JSON.stringify({ base, results, errors, failure: String(error) }, null, 2),
  );
  throw error;
} finally {
  await browser.close();
}
