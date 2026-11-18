import { useState, type ReactNode } from "react";
import { Button, Switch } from "antd";
import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { motion, useReducedMotion } from "motion/react";
import InlineHelp from "@/components/InlineHelp";
import { InteractiveCard } from "./InteractiveCard";
import styles from "./ServiceCard.module.less";

export function ServiceCard({
  name,
  description,
  metadata,
  enabled,
  onConfigure,
  onToggle,
  actions,
  surfaceId,
}: {
  surfaceId?: string;
  name: string;
  description?: ReactNode;
  metadata?: ReactNode;
  enabled: boolean;
  onConfigure: () => void;
  onToggle: () => Promise<void> | void;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  const reducedMotion = useReducedMotion();
  const [pending, setPending] = useState(false);
  return (
    <motion.div
      layout
      transition={{
        layout: reducedMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 340, damping: 36 },
      }}
    >
      <InteractiveCard
        tilt={0}
        layoutId={reducedMotion ? undefined : surfaceId}
        style={{ borderRadius: 20 }}
        className={styles.card}
        onClick={(event) => {
          if (
            !(event.target instanceof Element) ||
            event.target.closest(
              'button, a, input, [role="button"], [role="switch"]',
            )
          )
            return;
          onConfigure();
        }}
      >
        <div className={styles.heading}>
          <h3>
            <button type="button" onClick={onConfigure}>
              {name}
            </button>
          </h3>
          {description && <InlineHelp>{description}</InlineHelp>}
        </div>
        <div className={styles.metadata}>{metadata}</div>
        <div className={styles.actions}>
          <Button
            type="text"
            icon={<Settings2 size={16} />}
            onClick={onConfigure}
          >
            {t("common.configure")}
          </Button>
          <div className={styles.trailing}>
            {actions}
            <Switch
              checked={enabled}
              loading={pending}
              aria-label={`${t(
                enabled ? "common.disable" : "common.enable",
              )}: ${name}`}
              onChange={async () => {
                setPending(true);
                try {
                  await onToggle();
                } finally {
                  setPending(false);
                }
              }}
            />
          </div>
        </div>
      </InteractiveCard>
    </motion.div>
  );
}
