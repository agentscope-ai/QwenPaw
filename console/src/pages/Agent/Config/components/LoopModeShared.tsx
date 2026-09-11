import { useState, type ReactNode } from "react";
import { Tag } from "@agentscope-ai/design";
import { ChevronDown, ChevronRight, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";
import loopStyles from "./AgentLoopCard.module.less";

/**
 * One stage of a built-in loop template: a locked, collapsible card with
 * an icon, a title, a one-line description and optional details. `extra`
 * renders a control (typically a Switch) at the right edge of the header,
 * outside the expand button so it stays a valid, focusable control.
 */
export function LockedGateCard({
  icon,
  title,
  description,
  extra,
  children,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  extra?: ReactNode;
  children?: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const summary = (
    <button
      type="button"
      className={loopStyles.gateSummary}
      aria-expanded={expanded}
      onClick={() => setExpanded((value) => !value)}
    >
      <span className={loopStyles.lockSlot}>
        <Lock size={14} />
      </span>
      <span className={loopStyles.gateIcon}>{icon}</span>
      <span className={loopStyles.gateCopy}>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
    </button>
  );
  return (
    <div className={loopStyles.gateCard}>
      {extra ? (
        <div className={loopStyles.gateSummaryRow}>
          {summary}
          <span className={loopStyles.gateExtra}>{extra}</span>
        </div>
      ) : (
        summary
      )}
      {expanded && children ? (
        <div className={loopStyles.gateDetails}>{children}</div>
      ) : null}
    </div>
  );
}

/** The "Built-in · pipeline locked" banner at the top of a built-in template. */
export function BuiltInIntro({ description }: { description: string }) {
  const { t } = useTranslation();
  return (
    <div className={loopStyles.builtInIntro}>
      <div className={loopStyles.builtInIntroMain}>
        <Tag className={loopStyles.builtInTag}>
          <Lock size={11} />
          {t("agentConfig.loopMode.builtIn", "Built-in")}
        </Tag>
        <p>{description}</p>
      </div>
      <span className={loopStyles.builtInNote}>
        <Lock size={12} />
        {t(
          "agentConfig.loopMode.builtInNote",
          "Pipeline locked · Values editable",
        )}
      </span>
    </div>
  );
}
