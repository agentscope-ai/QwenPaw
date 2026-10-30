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
    approval_request?: {
      kind: string;
      inspection: { target_id: string };
      subject: { revision: string };
    };
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

  it.each([false, true])(
    "preserves the authenticated handoff destination (approval=%s)",
    async (approval) => {
      const expectedRoute =
        "/project/project-1" +
        (approval
          ? "?approvalKind=review&approvalTarget=review-7&approvalRevision=7"
          : "");
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
          registerRoutes: (
            _pluginId: string,
            nextRoutes: RegisteredRoute[],
          ) => {
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
      await waitFor(() =>
        expect(resolveHandoff).toHaveBeenCalledWith("handoff-1"),
      );

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
          ...(approval
            ? {
                approval_request: {
                  kind: "review",
                  inspection: { target_id: "review-7" },
                  subject: { revision: "7" },
                },
              }
            : {}),
          project_ref: {
            app_id: "qwenpaw-creator",
            project_id: "project-1",
            kind: "creator-project",
          },
        },
      });

      await waitFor(() => {
        expect(window.location.search).toBe("");
        expect(window.location.hash).toBe(`#${expectedRoute}`);
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
      expect(window.location.hash).toBe(`#${expectedRoute}`);
      expect(postMessage).toHaveBeenCalledWith(
        {
          type: "qwenpaw-creator:restore-route",
          path: expectedRoute,
        },
        "*",
      );

      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", {
            source: frame.contentWindow,
            data: {
              type: "qwenpaw-creator:navigation",
              path: expectedRoute,
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
    },
  );
});
