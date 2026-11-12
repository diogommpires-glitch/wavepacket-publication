import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

const root = fileURLToPath(new URL('../../', import.meta.url));
const venvPython = new URL(
  process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python',
  import.meta.url,
);
const python =
  process.env.WAVEPACKET_PYTHON ?? (existsSync(venvPython) ? fileURLToPath(venvPython) : 'python');
// An isolated empty run directory avoids reading or modifying the user's experiment records.
const exported = spawnSync(
  python,
  [
    '-c',
    [
      'import json, tempfile',
      'from pathlib import Path',
      'from wavepacket.api import create_app',
      "Path('frontend/.tmp').mkdir(exist_ok=True)",
      "with tempfile.TemporaryDirectory(dir='frontend/.tmp') as folder:",
      '    app = create_app(Path(folder))',
      '    print(json.dumps(app.openapi(), sort_keys=True, indent=2))',
    ].join('\n'),
  ],
  { cwd: root, encoding: 'utf8' },
);
if (exported.status !== 0)
  throw new Error(`OpenAPI export failed:\n${exported.stderr || exported.error}`);
const schema = JSON.parse(exported.stdout);
for (const name of ['SimulationConfig', 'RunRecord', 'Frame']) {
  if (!schema.components?.schemas?.[name])
    throw new Error(`OpenAPI is missing ${name}; generate against the current backend.`);
}
const schemaText = `${JSON.stringify(schema, null, 2)}\n`;
const contract = astToString(await openapiTS(schema));
const output = new URL('../src/generated/api.ts', import.meta.url);
const schemaPath = new URL('../openapi.json', import.meta.url);
if (process.argv.includes('--check')) {
  const [currentSchema, currentContract] = await Promise.all([
    readFile(schemaPath, 'utf8'),
    readFile(output, 'utf8'),
  ]);
  if (currentSchema !== schemaText || currentContract !== contract) {
    throw new Error(
      'Generated API contracts are stale. Run npm run generate:api and review the schema diff.',
    );
  }
  console.log('OpenAPI and TypeScript contracts match the current backend.');
} else {
  await mkdir(new URL('../src/generated/', import.meta.url), { recursive: true });
  await writeFile(schemaPath, schemaText);
  await writeFile(output, contract);
  console.log('Generated OpenAPI and TypeScript contracts from the current backend.');
}
