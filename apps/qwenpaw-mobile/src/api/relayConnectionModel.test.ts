import assert from "node:assert/strict";
import test from "node:test";

import { connectRelayWithRetry } from "./relayConnectionModel";

test("an expired WSS ticket is exchanged once before surfacing failure", async () => {
  const issuedTickets: string[] = [];
  const result = await connectRelayWithRetry(async () => {
    const ticket = `ticket-${issuedTickets.length + 1}`;
    issuedTickets.push(ticket);
    if (ticket === "ticket-1") throw new Error("ticket expired");
    return "connected";
  });

  assert.equal(result, "connected");
  assert.deepEqual(issuedTickets, ["ticket-1", "ticket-2"]);
});
