import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";

export interface PluginSettingsContext {
  source: string;
  routeId: string;
  returnTo: string;
}

export interface SettingsNavigationState {
  settingsReturnTo?: string;
  /** Null explicitly exits settings, even if the destination is the same plugin. */
  settingsPluginContext?: PluginSettingsContext | null;
}

/** Keep settings origin per history entry while navigating within a plugin. */
export function usePluginSettingsNavigation(
  route: { id: string; source: string } | undefined,
  settingsOnly: boolean,
) {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const [retainedContext, setRetainedContext] =
    useState<PluginSettingsContext | null>(null);
  const state = location.state as SettingsNavigationState | null;
  const storedContext = state?.settingsPluginContext;
  const source = route?.source;
  const routeId = route?.id;
  const returnTo = state?.settingsReturnTo || "/chat";
  const directLinkContext = useMemo(
    () =>
      settingsOnly && source && source !== "core" && routeId
        ? { source, routeId, returnTo }
        : null,
    [settingsOnly, source, routeId, returnTo],
  );
  const context =
    storedContext === null || !source || source === "core"
      ? null
      : storedContext?.source === source
      ? storedContext
      : navigationType !== "POP" && retainedContext?.source === source
      ? retainedContext
      : directLinkContext;

  useEffect(() => {
    setRetainedContext(context);
    if (context && storedContext !== context) {
      // Replace preserves the history stack, URL and plugin-provided state.
      navigate(
        {
          pathname: location.pathname,
          search: location.search,
          hash: location.hash,
        },
        {
          replace: true,
          state: { ...location.state, settingsPluginContext: context },
        },
      );
    }
  }, [context, storedContext, location, navigate]);

  return context;
}
