import { useTranslation } from "react-i18next";
import { fetchDataSources, type DataSourceRecord } from "../lib/data-sources";
import { resolveBackendSessionId } from "../lib/session-id";
import type { HostBundle } from "../types";
import { navigateDataConnectionAdd } from "./navigation";
import {
  resolveSelectedDataSourceId,
  writeSelectedDataSourceId,
} from "./data-source-selection";

function resolveSessionStorageKey(currentSessionId?: string | null): string {
  return resolveBackendSessionId(currentSessionId) || "default";
}

function useCurrentSessionId(React: HostBundle["React"]): string | null {
  const { useSyncExternalStore } = React;
  return useSyncExternalStore(
    (cb) => {
      const timer = window.setInterval(cb, 500);
      return () => window.clearInterval(timer);
    },
    () =>
      (window as Window & { currentSessionId?: string }).currentSessionId ||
      null,
    () => null,
  );
}

function createDatabaseIcon(React: HostBundle["React"]) {
  return function DatabaseIcon({ size = 14 }: { size?: number }) {
    return React.createElement(
      "svg",
      {
        width: size,
        height: size,
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 2,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        "aria-hidden": true,
      },
      React.createElement("ellipse", { cx: 12, cy: 5, rx: 9, ry: 3 }),
      React.createElement("path", { d: "M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" }),
      React.createElement("path", { d: "M3 12c0 1.66 4 3 9 3s9-1.34 9-3" }),
    );
  };
}

function createChevronDownIcon(React: HostBundle["React"]) {
  return function ChevronDownIcon({ size = 14 }: { size?: number }) {
    return React.createElement(
      "svg",
      {
        width: size,
        height: size,
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 2,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        "aria-hidden": true,
      },
      React.createElement("path", { d: "m6 9 6 6 6-6" }),
    );
  };
}

function createPlusIcon(React: HostBundle["React"]) {
  return function PlusIcon({ size = 14 }: { size?: number }) {
    return React.createElement(
      "svg",
      {
        width: size,
        height: size,
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 2,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        "aria-hidden": true,
      },
      React.createElement("path", { d: "M5 12h14" }),
      React.createElement("path", { d: "M12 5v14" }),
    );
  };
}

export function createDataSourceSelector(host: HostBundle) {
  const { React, antd } = host;
  const { useCallback, useEffect, useMemo, useState } = React;
  const { Button, Popover, Radio } = antd;
  const DatabaseIcon = createDatabaseIcon(React);
  const ChevronDownIcon = createChevronDownIcon(React);
  const PlusIcon = createPlusIcon(React);

  return function DataSourceSelector(): React.ReactElement {
    const { t } = useTranslation();
    const currentSessionId = useCurrentSessionId(React);
    const [open, setOpen] = useState(false);
    const [connections, setConnections] = useState<DataSourceRecord[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedId, setSelectedId] = useState("");

    const sessionKey = useMemo(
      () => resolveSessionStorageKey(currentSessionId),
      [currentSessionId],
    );

    useEffect(() => {
      let cancelled = false;
      setLoading(true);
      fetchDataSources()
        .then((items) => {
          if (!cancelled) setConnections(items);
        })
        .catch((error) => {
          console.error("[datapaw:data-source-selector] load failed:", error);
          if (!cancelled) setConnections([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }, []);

    useEffect(() => {
      if (loading) return;

      const connectionIds = connections.map((item) => item.id);
      const nextId = resolveSelectedDataSourceId(sessionKey, connectionIds);
      setSelectedId(nextId ?? "");

      if (nextId) {
        writeSelectedDataSourceId(sessionKey, nextId);
      }
    }, [connections, loading, sessionKey]);

    const selectedConnection = useMemo(
      () => connections.find((item) => item.id === selectedId),
      [connections, selectedId],
    );

    const handleSelect = useCallback(
      (value: string) => {
        setSelectedId(value);
        writeSelectedDataSourceId(sessionKey, value);
        setOpen(false);
      },
      [sessionKey],
    );

    const handleAddSource = useCallback(() => {
      setOpen(false);
      navigateDataConnectionAdd();
    }, []);

    const content = React.createElement(
      "div",
      { className: "datapaw-ds-panel" },
      React.createElement(
        "div",
        { className: "datapaw-ds-panel-title" },
        t("chat.dataSource.title"),
      ),
      loading
        ? React.createElement(
            "div",
            { className: "datapaw-ds-empty-hint" },
            t("common.loading"),
          )
        : connections.length === 0
          ? React.createElement(
              "div",
              { className: "datapaw-ds-empty-hint" },
              t("chat.dataSource.empty"),
            )
          : React.createElement(
              Radio.Group,
              {
                value: selectedId,
                onChange: (event: { target: { value: string } }) =>
                  handleSelect(event.target.value),
                className: "datapaw-ds-option-list",
              },
              connections.map((item) =>
                React.createElement(
                  "label",
                  {
                    key: item.id,
                    className: "datapaw-ds-option-row",
                    htmlFor: `datapaw-ds-${item.id}`,
                  },
                  React.createElement(
                    "span",
                    { className: "datapaw-ds-option-left" },
                    React.createElement(
                      "span",
                      { className: "datapaw-ds-option-label" },
                      item.name || item.type,
                    ),
                  ),
                  React.createElement(Radio, {
                    id: `datapaw-ds-${item.id}`,
                    value: item.id,
                  }),
                ),
              ),
            ),
      React.createElement(
        Button,
        {
          type: "default",
          className: "datapaw-ds-add-button",
          icon: React.createElement(PlusIcon),
          onClick: handleAddSource,
        },
        t("chat.dataSource.add"),
      ),
    );

    return React.createElement(
      Popover,
      {
        content,
        trigger: "click",
        placement: "topLeft",
        open,
        onOpenChange: setOpen,
      },
      React.createElement(
        "button",
        {
          type: "button",
          className: `datapaw-ds-trigger${open ? " datapaw-ds-trigger-open" : ""}`,
          "aria-expanded": open,
          "aria-haspopup": "listbox",
        },
        React.createElement(
          "span",
          { className: "datapaw-ds-trigger-icon" },
          React.createElement(DatabaseIcon),
        ),
        React.createElement(
          "span",
          null,
          selectedConnection?.name ?? t("chat.dataSource.label"),
        ),
        React.createElement(
          "span",
          { className: "datapaw-ds-trigger-chevron" },
          React.createElement(ChevronDownIcon),
        ),
      ),
    );
  };
}
