import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreatorHttpError, creatorRequest } from "@/api/creator/client";
import i18n from "@/i18n";
import {
  reportBackendAvailable,
  reportBackendUnavailable,
} from "@/lib/backendHealthSignal";
import { useCreatorBackendHealthStore } from "@/store/creatorBackendHealthStore";

/**
 * v2.0.6 problem 3: after an upgrade the host SPA catch-all answered Creator
 * requests with a plain-text 405, and users were shown the raw English status.
 * The client now translates that (and a non-envelope 404) into an actionable
 * BACKEND_UNAVAILABLE diagnostic and flags the backend-health store.
 */

function installFetch(make: () => Response | Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(make())),
  );
}

function resetHealth(): void {
  reportBackendAvailable();
  useCreatorBackendHealthStore.setState({
    phase: "checking",
    probing: false,
    everReady: false,
    error: null,
    checkedAt: null,
  });
}

describe("creator client backend-unavailable translation", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    resetHealth();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetHealth();
  });

  it("translates a plain-text 405 into BACKEND_UNAVAILABLE and flags the store", async () => {
    installFetch(
      () =>
        new Response("Method Not Allowed", {
          status: 405,
          statusText: "Method Not Allowed",
        }),
    );

    const settled = creatorRequest("/projects/p1/project");
    await expect(settled).rejects.toBeInstanceOf(CreatorHttpError);
    await expect(settled).rejects.toMatchObject({
      status: 405,
      code: "BACKEND_UNAVAILABLE",
      retryable: true,
      userMessage: i18n.t("api.backendUnavailable"),
      // The raw host status text never reaches the user.
      message: i18n.t("api.backendUnavailable"),
    });
    expect(useCreatorBackendHealthStore.getState().phase).toBe("unavailable");
  });

  it("keeps a real JSON 405 from the plugin backend and leaves health alone", async () => {
    installFetch(
      () =>
        new Response(JSON.stringify({ detail: "Method Not Allowed" }), {
          status: 405,
          headers: { "content-type": "application/json" },
        }),
    );

    await expect(creatorRequest("/projects/p1/project")).rejects.toMatchObject({
      status: 405,
      message: "Method Not Allowed",
    });
    expect(useCreatorBackendHealthStore.getState().phase).toBe("checking");
  });

  it("translates a non-Creator 404 the same way", async () => {
    installFetch(
      () =>
        new Response("<html>Not Found</html>", {
          status: 404,
          headers: { "content-type": "text/html" },
        }),
    );

    await expect(creatorRequest("/health")).rejects.toMatchObject({
      status: 404,
      code: "BACKEND_UNAVAILABLE",
      retryable: true,
    });
    expect(useCreatorBackendHealthStore.getState().phase).toBe("unavailable");
  });

  it("keeps a real Creator 404 envelope verbatim and leaves health alone", async () => {
    installFetch(
      () =>
        new Response(
          JSON.stringify({ code: "NOT_FOUND", message: "项目不存在" }),
          { status: 404, headers: { "content-type": "application/json" } },
        ),
    );

    await expect(creatorRequest("/projects/missing")).rejects.toMatchObject({
      status: 404,
      code: "NOT_FOUND",
      userMessage: "项目不存在",
    });
    expect(useCreatorBackendHealthStore.getState().phase).toBe("checking");
  });

  it("clears the unavailable phase as soon as a real response arrives", async () => {
    reportBackendUnavailable();
    expect(useCreatorBackendHealthStore.getState().phase).toBe("unavailable");

    installFetch(
      () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );

    await expect(creatorRequest("/health")).resolves.toEqual({ ok: true });
    const state = useCreatorBackendHealthStore.getState();
    expect(state.phase).toBe("ready");
    expect(state.everReady).toBe(true);
    expect(state.error).toBeNull();
  });
});
