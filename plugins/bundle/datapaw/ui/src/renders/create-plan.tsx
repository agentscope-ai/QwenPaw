import type { HostBundle } from "../types";
import { getSessionId } from "../lib/agent";
import { fetchTasksSummary } from "../lib/api";

/**
 * create_plan tool render — keep minimal UI only.
 * The full task card is injected separately (single datapaw_task_graph message).
 */
export function createCreatePlanRender(host: HostBundle) {
  const { React, antd } = host;
  const { useState, useEffect } = React;
  const { Spin } = antd;

  return function CreatePlanRender({
    data,
  }: {
    data: { status?: string };
  }) {
    const [loading, setLoading] = useState(data?.status === "IN_PROGRESS");

    useEffect(() => {
      if (data?.status !== "IN_PROGRESS") {
        setLoading(false);
        return;
      }
      const sessionId = getSessionId();
      if (!sessionId) {
        setLoading(false);
        return;
      }
      let cancelled = false;
      void fetchTasksSummary(sessionId).finally(() => {
        if (!cancelled) setLoading(false);
      });
      return () => {
        cancelled = true;
      };
    }, [data?.status]);

    if (!loading) return null;

    return React.createElement(
      "div",
      { style: { padding: "8px 0", color: "rgba(0,0,0,0.45)" } },
      React.createElement(Spin, { size: "small" }),
      " ",
      "Loading task plan…",
    );
  };
}
