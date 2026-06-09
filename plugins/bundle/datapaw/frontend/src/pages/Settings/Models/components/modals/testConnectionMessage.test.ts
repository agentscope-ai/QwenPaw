import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { getTestConnectionFailureDetail } from "./testConnectionMessage";

describe("getTestConnectionFailureDetail", () => {
  it("treats generic failures case-insensitively", () => {
    assert.equal(getTestConnectionFailureDetail("connection failed"), null);
  });

  it("ignores trailing periods on generic failures", () => {
    assert.equal(getTestConnectionFailureDetail("Connection failed."), null);
  });

  it("drops redundant generic detail after stripping the prefix", () => {
    assert.equal(
      getTestConnectionFailureDetail("Connection failed: Connection failed"),
      null,
    );
  });
});
