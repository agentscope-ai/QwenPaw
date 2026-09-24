import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

type RegisteredRoute = {
  path: string;
  component: React.ComponentType;
};

type Handoff = {
  target_app_id: string;
  context: {
    project_ref: {
      app_id: string;
      project_id: string;
      kind: string;
    };
  };
};

describe("Creator plugin handoff", () => {
  beforeEach(() => {
    vi.resetModules();
    window.history.replaceState({}, "", "/");
    delete (window as typeof window & { QwenPaw?: unknown }).QwenPaw;
  });

  it("does not let initial iframe navigation discard a pending handoff", async () => {
    const routes: RegisteredRoute[] = [];
    let resolveHandoffRequest: (handoff: Handoff) => void = () => undefined;
    const resolveHandoff = vi.fn(
      () =>
        new Promise<Handoff>((resolve) => {
          resolveHandoffRequest = resolve;
        }),
    );

    Object.defineProperty(window, "QwenPaw", {
      configurable: true,
      value: {
        host: {
          React,
          getApiUrl: (path: string) => `/api${path}`,
        },
        paw: {
          forApp: () => ({ apps: { resolveHandoff } }),
        },
        registerRoutes: (_pluginId: string, nextRoutes: RegisteredRoute[]) => {
          routes.push(...nextRoutes);
        },
      },
    });
    window.history.replaceState(
      {},
      "",
      "/apps/qwenpaw-creator?handoff=handoff-1",
    );

    await import("../../../plugin-entry.js");
    const view = render(React.createElement(routes[0].component));
    const frame = view.getByTitle("QwenPaw Creator") as HTMLIFrameElement;
    const postMessage = vi.spyOn(frame.contentWindow!, "postMessage");
    await waitFor(() => expect(resolveHandoff).toHaveBeenCalledWith("handoff-1"));

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: frame.contentWindow,
          data: { type: "qwenpaw-creator:navigation", path: "/" },
        }),
      );
    });
    expect(window.location.search).toBe("?handoff=handoff-1");

    resolveHandoffRequest({
      target_app_id: "qwenpaw-creator",
      context: {
        project_ref: {
          app_id: "qwenpaw-creator",
          project_id: "project-1",
          kind: "creator-project",
        },
      },
    });

    await waitFor(() => {
      expect(window.location.search).toBe("");
      expect(window.location.hash).toBe("#/project/project-1");
    });

    postMessage.mockClear();
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: frame.contentWindow,
          data: { type: "qwenpaw-creator:navigation", path: "/" },
        }),
      );
    });
    expect(window.location.hash).toBe("#/project/project-1");
    expect(postMessage).toHaveBeenCalledWith(
      {
        type: "qwenpaw-creator:restore-route",
        path: "/project/project-1",
      },
      "*",
    );

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: frame.contentWindow,
          data: {
            type: "qwenpaw-creator:navigation",
            path: "/project/project-1",
          },
        }),
      );
      window.dispatchEvent(
        new MessageEvent("message", {
          source: frame.contentWindow,
          data: {
            type: "qwenpaw-creator:navigation",
            path: "/project/project-1/assets",
          },
        }),
      );
    });
    expect(window.location.hash).toBe("#/project/project-1/assets");
  });
});
