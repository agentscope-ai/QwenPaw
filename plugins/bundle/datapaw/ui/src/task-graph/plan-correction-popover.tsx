import type { HostBundle } from "../types";
import type { PlanSnapshot } from "./types";
import { planToEditableYaml } from "./plan-to-yaml";
import { tTaskGraph } from "./i18n";
import { createYamlCodeEditor } from "./yaml-editor";
import { createCloseIcon } from "../lib/icons";

export function createPlanCorrectionPopover(host: HostBundle) {
  const { React, antd } = host;
  const { useCallback, useEffect, useState } = React;
  const { Popover, Button } = antd;
  const CloseIcon = createCloseIcon(React);
  const YamlCodeEditor = createYamlCodeEditor(host);

  return function PlanCorrectionPopover({
    plan,
    children,
    onConfirm,
  }: {
    plan: PlanSnapshot;
    children: React.ReactNode;
    onConfirm?: (yaml: string) => void;
  }) {
    const [open, setOpen] = useState(false);
    const [yaml, setYaml] = useState(() => planToEditableYaml(plan));

    useEffect(() => {
      if (open) {
        setYaml(planToEditableYaml(plan));
      }
    }, [open, plan]);

    const handleCancel = useCallback(() => {
      setOpen(false);
    }, []);

    const handleConfirm = useCallback(() => {
      onConfirm?.(yaml);
      setOpen(false);
    }, [onConfirm, yaml]);

    const content = React.createElement(
      "div",
      { className: "datapaw-plan-correction-panel" },
      React.createElement(
        "div",
        { className: "datapaw-plan-correction-header" },
        React.createElement(
          "span",
          { className: "datapaw-plan-correction-title" },
          tTaskGraph("planCorrection"),
        ),
        React.createElement(
          "button",
          {
            type: "button",
            className: "datapaw-plan-correction-close",
            "aria-label": tTaskGraph("close"),
            onClick: handleCancel,
          },
          React.createElement(CloseIcon),
        ),
      ),
      React.createElement(YamlCodeEditor, { value: yaml, onChange: setYaml }),
      React.createElement(
        "div",
        { className: "datapaw-plan-correction-footer" },
        React.createElement(
          Button,
          {
            type: "default",
            className: "datapaw-plan-correction-cancel",
            onClick: handleCancel,
          },
          tTaskGraph("cancel"),
        ),
        React.createElement(
          Button,
          {
            type: "primary",
            className: "datapaw-plan-correction-confirm",
            onClick: handleConfirm,
          },
          tTaskGraph("confirmUpdate"),
        ),
      ),
    );

    return React.createElement(
      Popover,
      {
        content,
        trigger: "click",
        placement: "rightTop",
        open,
        onOpenChange: setOpen,
        arrow: true,
        autoAdjustOverflow: true,
        overlayClassName: "datapaw-plan-correction-popover",
        overlayInnerStyle: { padding: 0 },
      },
      React.createElement(
        "span",
        {
          className: "datapaw-plan-correction-trigger",
          onClick: (event: { stopPropagation: () => void }) =>
          event.stopPropagation(),
        },
        children,
      ),
    );
  };
}
