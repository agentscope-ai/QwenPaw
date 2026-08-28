import assert from "node:assert/strict";
import test from "node:test";

import {
  connectionTimeoutMessage,
  startConnectionAttempt,
} from "./connectionAttempt";

test("connection attempt aborts after its timeout", async () => {
  const attempt = startConnectionAttempt(5);
  await new Promise((resolve) => setTimeout(resolve, 15));

  assert.equal(attempt.signal.aborted, true);
  assert.equal(attempt.didTimeout(), true);
  attempt.dispose();
});

test("manual cancellation is distinct from a timeout", () => {
  const attempt = startConnectionAttempt(1_000);
  attempt.cancel();

  assert.equal(attempt.signal.aborted, true);
  assert.equal(attempt.didTimeout(), false);
  attempt.dispose();
});

test("localhost timeout explains Android host addressing", () => {
  assert.match(
    connectionTimeoutMessage("http://127.0.0.1:8088"),
    /10\.0\.2\.2/,
  );
});

test("LAN timeout explains server binding", () => {
  assert.match(
    connectionTimeoutMessage("http://192.168.1.23:8088"),
    /--host 0\.0\.0\.0/,
  );
});
