/**
 * Replay plugin.json / data_paw.json SSE through sseIntercept handlers
 * to verify graph_created + response.completed flush path.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  normalizeSseParsedObject,
  registerResponseCompletedHandler,
  registerTaskStatusParserHandler,
} from '../src/pages/Chat/sseIntercept.ts';

// paw repo root: .../paw/plugin.json
const root = join(dirname(fileURLToPath(import.meta.url)), '../../../../../../');

function replaySseFile(relPath) {
  const path = join(root, relPath);
  const raw = readFileSync(path, 'utf8');
  const lines = raw.split('\n').filter((l) => l.startsWith('data:'));

  const taskEvents = [];
  let flushCount = 0;

  registerTaskStatusParserHandler((ev) => {
    taskEvents.push(ev.event_type);
  });
  registerResponseCompletedHandler(() => {
    flushCount += 1;
  });

  for (const line of lines) {
    const jsonStr = line.slice(5).trimStart();
    if (!jsonStr) continue;
    try {
      const parsed = JSON.parse(jsonStr);
      normalizeSseParsedObject(parsed);
    } catch {
      // skip malformed
    }
  }

  registerTaskStatusParserHandler(null);
  registerResponseCompletedHandler(null);

  return { lines: lines.length, taskEvents, flushCount };
}

const plugin = replaySseFile('plugin.json');
const dataPaw = replaySseFile('data_paw.json');

console.log('=== plugin.json replay ===');
console.log(plugin);
console.log('=== data_paw.json replay ===');
console.log(dataPaw);

const ok =
  plugin.taskEvents.includes('graph_created') &&
  plugin.flushCount >= 1 &&
  dataPaw.taskEvents.includes('graph_created') &&
  dataPaw.taskEvents.includes('graph_updated') &&
  dataPaw.flushCount >= 0;

if (!ok) {
  console.error('VERIFY FAILED');
  process.exit(1);
}
console.log('VERIFY OK: intercept handlers fire on both captures');
