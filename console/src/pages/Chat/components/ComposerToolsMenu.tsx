import { useEffect, useRef, useState } from "react";
import { Dropdown } from "antd";
import {
  CircleDot,
  Cpu,
  Folder,
  Gauge,
  Mic,
  Paperclip,
  Plus,
  Settings,
  Shield,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./ComposerToolsMenu.module.less";

const toolIcons = {
  speech: Mic,
  attach: Paperclip,
  loop: CircleDot,
  model: Cpu,
  context: Gauge,
  "project-directory": Folder,
  approval: Shield,
};

type Tool = {
  key: string;
  kind: keyof typeof toolIcons | "plugin";
  label: string;
  value: string;
  button: HTMLButtonElement | null;
  disabled: boolean;
};

// Read the mounted controls when opening the menu. Their click handlers remain
// the single owner of uploads, recording and the individual settings dialogs.
function readTools(bottom: HTMLElement): Tool[] {
  const roots = bottom.querySelectorAll(
    '[class$="-sender-prefix"], [data-composer-actions]',
  );
  return Array.from(roots).flatMap((root) =>
    Array.from(
      root.querySelectorAll<HTMLElement>(
        "[data-composer-responsive-item], [data-composer-context], button:not([data-composer-responsive-item] button):not([data-composer-context] button)",
      ),
    ).map((element, index) => {
      const button =
        element instanceof HTMLButtonElement
          ? element
          : element.querySelector<HTMLButtonElement>("button");
      const kind =
        element.dataset.composerResponsiveItem ||
        (element.hasAttribute("data-composer-context")
          ? "context"
          : button?.dataset.composerTool ||
            (Array.from(button?.classList ?? []).some((name) =>
              name.endsWith("-sender-actions-btn"),
            )
              ? "speech"
              : "plugin"));
      const valueNode = element.querySelector(
        "[data-composer-collapse-content]",
      );
      return {
        key: `${kind}-${index}`,
        kind: kind as Tool["kind"],
        label:
          button?.getAttribute("aria-label") ||
          button?.textContent?.trim() ||
          "",
        value:
          button?.dataset.composerValue ??
          (
            valueNode?.querySelector("strong")?.textContent ||
            valueNode?.textContent ||
            ""
          ).trim(),
        button,
        disabled:
          !button ||
          button.disabled ||
          button.getAttribute("aria-disabled") === "true",
      };
    }),
  );
}

export default function ComposerToolsMenu({
  className,
}: {
  className: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [tools, setTools] = useState<Tool[]>([]);

  useEffect(() => {
    const bottom = ref.current?.closest<HTMLElement>(
      '[class$="-sender-content-bottom"]',
    );
    if (!bottom) return;
    const observer = new MutationObserver(() => {
      if (bottom.dataset.composerOverflow !== "true") setOpen(false);
    });
    observer.observe(bottom, {
      attributes: true,
      attributeFilter: ["data-composer-overflow"],
    });
    return () => observer.disconnect();
  }, []);

  return (
    <Dropdown
      trigger={["click"]}
      placement="topLeft"
      align={{ overflow: { adjustX: true, adjustY: true, shiftX: true } }}
      open={open}
      autoFocus
      overlayClassName={styles.popup}
      onOpenChange={(next) => {
        const bottom = ref.current?.closest<HTMLElement>(
          '[class$="-sender-content-bottom"]',
        );
        if (next && bottom) setTools(readTools(bottom));
        setOpen(next);
      }}
      menu={{
        items: tools.map((tool) => {
          const Icon = tool.kind === "plugin" ? Settings : toolIcons[tool.kind];
          return {
            key: tool.key,
            disabled: tool.disabled,
            icon: <Icon size={18} />,
            label: (
              <span className={styles.row}>
                <span>
                  {tool.kind === "plugin"
                    ? tool.label
                    : t(`chat.composer.menu.${tool.kind}`)}
                </span>
                {tool.value && (
                  <span className={styles.value} title={tool.value}>
                    {tool.value}
                  </span>
                )}
              </span>
            ),
          };
        }),
        onClick: ({ key }) => {
          const tool = tools.find((item) => item.key === key);
          if (tool?.button?.isConnected && !tool.button.disabled)
            tool.button.click();
          setOpen(false);
        },
      }}
    >
      <button
        ref={ref}
        type="button"
        className={className}
        aria-label={t("chat.composer.tools")}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <Plus size="1em" />
      </button>
    </Dropdown>
  );
}
