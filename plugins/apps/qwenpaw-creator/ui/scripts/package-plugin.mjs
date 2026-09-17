import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distRoot = path.join(uiRoot, 'dist');

await mkdir(distRoot, { recursive: true });
const entryTemplate = await readFile(path.join(uiRoot, 'plugin-entry.js'), 'utf8');
const placeholder = '__CREATOR_BUILD_ID__';
if (!entryTemplate.includes(placeholder)) {
  throw new Error(`plugin entry is missing build id placeholder: ${placeholder}`);
}
const appIndex = await readFile(path.join(distRoot, 'app', 'index.html'));
const buildId = createHash('sha256').update(appIndex).digest('hex').slice(0, 12);
const entry = entryTemplate.replaceAll(placeholder, buildId);
await writeFile(path.join(distRoot, 'index.js'), entry, 'utf8');
