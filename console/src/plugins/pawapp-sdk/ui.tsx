import React, { useEffect, useRef } from "react";
import { routeRegistry } from "../registry/store";
import type {
  PawChatUiNamespace,
  PawDisposable,
  PawPageRegistration,
  PawUiNamespace,
} from "./types";
import { normalizeAppId, normalizeAppRelativePath } from "./scope";

function mountedComponent(
  mount: NonNullable<PawPageRegistration["mount"]>,
): React.ComponentType {
  return function PawAppMountedPage() {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
      if (!ref.current) return;
      const cleanup = mount(ref.current);
      return () => {
        if (typeof cleanup === "function") cleanup();
        else cleanup?.dispose();
      };
    }, []);
    return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
  };
}

function requireChat() {
  if (!window.QwenPaw.chat) {
    throw new Error("PawApp chat UI capabilities are unavailable");
  }
  return window.QwenPaw.chat;
}

type AppIdProvider = string | (() => string);

function resolveAppId(provider: AppIdProvider): string {
  return typeof provider === "function" ? provider() : provider;
}

function createChatUiNamespace(provider: AppIdProvider): PawChatUiNamespace {
  return {
    theme: {
      set: (partial) =>
        requireChat().theme.set(resolveAppId(provider), partial),
    },
    welcome: {
      set: (partial) =>
        requireChat().welcome.set(resolveAppId(provider), partial),
      render: (value) =>
        requireChat().welcome.render(resolveAppId(provider), value),
    },
    leftHeader: {
      set: (partial) =>
        requireChat().leftHeader.set(resolveAppId(provider), partial),
      render: (node) =>
        requireChat().leftHeader.render(resolveAppId(provider), node),
    },
    rightHeader: {
      add: (node, opts) =>
        requireChat().rightHeader.add(resolveAppId(provider), node, opts),
    },
    sender: {
      set: (partial) =>
        requireChat().sender.set(resolveAppId(provider), partial),
      addPrefix: (node, opts) =>
        requireChat().sender.addPrefix(resolveAppId(provider), node, opts),
      addSuggestion: (item) =>
        requireChat().sender.addSuggestion(resolveAppId(provider), item),
    },
    actions: {
      add: (action) =>
        requireChat().actions.add(resolveAppId(provider), action),
    },
    requestActions: {
      add: (action) =>
        requireChat().requestActions.add(resolveAppId(provider), action),
    },
    requestPayload: {
      add: (transform, opts) =>
        requireChat().requestPayload.add(
          resolveAppId(provider),
          transform,
          opts,
        ),
    },
    request: {
      render: (render) =>
        requireChat().request.render(resolveAppId(provider), render),
      prepend: (render, opts) =>
        requireChat().request.prepend(resolveAppId(provider), render, opts),
      append: (render, opts) =>
        requireChat().request.append(resolveAppId(provider), render, opts),
    },
    response: {
      set: (partial) =>
        requireChat().response.set(resolveAppId(provider), partial),
      render: (render) =>
        requireChat().response.render(resolveAppId(provider), render),
      prepend: (render, opts) =>
        requireChat().response.prepend(resolveAppId(provider), render, opts),
      append: (render, opts) =>
        requireChat().response.append(resolveAppId(provider), render, opts),
    },
    toolRender: (toolName, render) =>
      requireChat().toolRender(resolveAppId(provider), toolName, render),
    approvalRender: (sourceType, render) =>
      requireChat().approval.render(resolveAppId(provider), sourceType, render),
    card: (cardName, render) =>
      requireChat().card(resolveAppId(provider), cardName, render),
    disposeAll: () => requireChat().disposeAll(resolveAppId(provider)),
  };
}

export function createUiNamespace(provider: AppIdProvider): PawUiNamespace {
  return {
    registerPage(registration): PawDisposable {
      const appId = normalizeAppId(resolveAppId(provider));
      if (!!registration.component === !!registration.mount) {
        throw new Error(
          "PawApp page registration requires exactly one of component or mount",
        );
      }
      const path = normalizeAppRelativePath(
        registration.path ?? `/apps/${appId}`,
      );
      if (path !== `/apps/${appId}` && !path.startsWith(`/apps/${appId}/`)) {
        throw new Error(`PawApp page path must stay under /apps/${appId}`);
      }
      const Component =
        registration.component ?? mountedComponent(registration.mount!);
      return routeRegistry.add(appId, {
        id: `pawapp:${appId}:${path}`,
        path,
        component: Component,
      });
    },
    chat: createChatUiNamespace(provider),
  };
}
