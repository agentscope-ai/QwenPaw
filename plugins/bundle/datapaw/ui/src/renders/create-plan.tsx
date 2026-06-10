import type { HostBundle } from "../types";

const IN_PROGRESS = "in_progress";

/**
 * create_plan tool render — loading indicator only.
 * GET /api/tasks is triggered exclusively from chat SSE when name === create_plan
 * (see patches/task-card.ts handlePlanToolInStream).
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
    const isLoading = data?.status === IN_PROGRESS;
    const [showSpinner, setShowSpinner] = useState(isLoading);

    useEffect(() => {
      setShowSpinner(isLoading);
    }, [isLoading]);

    if (!showSpinner) return null;

    return React.createElement(
      "div",
      { style: { padding: "8px 0", color: "rgba(0,0,0,0.45)" } },
      React.createElement(Spin, { size: "small" }),
      " ",
      "Loading task plan…",
    );
  };
}
