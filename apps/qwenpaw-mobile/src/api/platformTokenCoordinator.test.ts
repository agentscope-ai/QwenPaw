import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import { PlatformTokenCoordinator } from "./platformTokenCoordinator";

interface TestSession {
  accessToken: string;
  expiresAt: number;
  refreshToken: string;
}

test("local Platform mock rotates one token for concurrent requests", async () => {
  let refreshes = 0;
  const server = createServer((request, response) => {
    if (request.method !== "POST" || request.url !== "/refresh") {
      response.writeHead(404).end();
      return;
    }
    refreshes += 1;
    response.setHeader("Content-Type", "application/json");
    response.end(
      JSON.stringify({
        accessToken: `access-${refreshes}`,
        expiresIn: 3600,
        refreshToken: `refresh-${refreshes}`,
      }),
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert(address && typeof address === "object");
  let session: TestSession = {
    accessToken: "expired-access",
    expiresAt: 0,
    refreshToken: "initial-refresh",
  };
  const coordinator = new PlatformTokenCoordinator<TestSession>({
    earlyRefreshSeconds: 300,
    load: async () => session,
    now: () => 1_000,
    refresh: async () => {
      const response = await fetch(`http://127.0.0.1:${address.port}/refresh`, {
        method: "POST",
      });
      const payload = (await response.json()) as {
        accessToken: string;
        expiresIn: number;
        refreshToken: string;
      };
      session = {
        accessToken: payload.accessToken,
        expiresAt: 1_000 + payload.expiresIn,
        refreshToken: payload.refreshToken,
      };
      return session;
    },
  });
  try {
    const tokens = await Promise.all([
      coordinator.accessToken(),
      coordinator.accessToken(),
      coordinator.accessToken(),
    ]);
    assert.deepEqual(tokens, ["access-1", "access-1", "access-1"]);
    assert.equal(refreshes, 1);

    const stale401 = await coordinator.afterUnauthorized("expired-access");
    assert.equal(stale401?.accessToken, "access-1");
    assert.equal(refreshes, 1);
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  }
});
