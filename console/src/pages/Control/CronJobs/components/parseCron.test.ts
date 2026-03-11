import test from "node:test";
import assert from "node:assert/strict";

import { parseCron, serializeCron } from "./parseCron.ts";

test("parseCron keeps plain daily schedules as structured daily", () => {
  const parsed = parseCron("0 9 * * *");

  assert.equal(parsed.type, "daily");
  assert.equal(parsed.hour, 9);
  assert.equal(parsed.minute, 0);
  assert.equal(serializeCron(parsed), "0 9 * * *");
});

test("parseCron keeps plain weekly schedules as structured weekly", () => {
  const parsed = parseCron("0 9 * * 1,3,5");

  assert.equal(parsed.type, "weekly");
  assert.deepEqual(parsed.daysOfWeek, [1, 3, 5]);
  assert.equal(serializeCron(parsed), "0 9 * * 1,3,5");
});

test("parseCron treats hour ranges as custom to avoid lossy edits", () => {
  const parsed = parseCron("0 8-18 * * *");

  assert.deepEqual(parsed, { type: "custom", rawCron: "0 8-18 * * *" });
  assert.equal(serializeCron(parsed), "0 8-18 * * *");
});

test("parseCron treats complex hour and weekday ranges as custom", () => {
  const parsed = parseCron("0 9-17 * * 1-5");

  assert.deepEqual(parsed, { type: "custom", rawCron: "0 9-17 * * 1-5" });
  assert.equal(serializeCron(parsed), "0 9-17 * * 1-5");
});

test("parseCron treats lists and step expressions as custom", () => {
  const listParsed = parseCron("0 8,10,12 * * *");
  const stepParsed = parseCron("*/15 8-18 * * *");

  assert.deepEqual(listParsed, {
    type: "custom",
    rawCron: "0 8,10,12 * * *",
  });
  assert.deepEqual(stepParsed, {
    type: "custom",
    rawCron: "*/15 8-18 * * *",
  });
  assert.equal(serializeCron(listParsed), "0 8,10,12 * * *");
  assert.equal(serializeCron(stepParsed), "*/15 8-18 * * *");
});
