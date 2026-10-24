import type { ReactNode } from "react";
import { Tabs } from "@agentscope-ai/design";
import { motion, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import styles from "./RuntimeWorkbench.module.less";

const groups = [
  { id: "workspace", keys: ["reactAgent"] },
  { id: "execution", keys: ["agentLoop", "toolExecutionLevel"] },
  { id: "recovery", keys: ["llmRetry", "llmRateLimiter"] },
  { id: "context", keys: ["lightContext"] },
  { id: "memory", keys: ["remeLightMemory", "embeddingModel"] },
];

export function RuntimeWorkbench({
  items = [],
  initialKey,
  onNavigate,
  onSectionChange,
}: {
  items: { key: string; children?: ReactNode }[];
  initialKey?: string | null;
  onNavigate: () => Promise<boolean>;
  onSectionChange: (key: string) => void;
}) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const active =
    groups.find((group) => group.keys.includes(initialKey || "")) || groups[0];
  return (
    <Tabs
      className={styles.workbench}
      activeKey={active.id}
      onChange={async (id) => {
        const target = groups.find((group) => group.id === id);
        if (target && (await onNavigate())) onSectionChange(target.keys[0]);
      }}
      items={groups.map(({ id, keys }) => ({
        key: id,
        label: t(`runtimeDesign.${id}`),
        children: (
          <motion.div
            className={styles.modules}
            initial={false}
            animate={{ opacity: active.id === id ? 1 : 0 }}
            transition={{ duration: reduced ? 0 : 0.15 }}
          >
            {items
              .filter(
                (item) =>
                  keys.includes(item.key) ||
                  (id === "memory" &&
                    !groups.some((group) => group.keys.includes(item.key))),
              )
              .map((item) => (
                <section
                  key={item.key}
                  data-runtime-key={item.key}
                  className={styles.module}
                >
                  {item.children}
                </section>
              ))}
          </motion.div>
        ),
      }))}
    />
  );
}
