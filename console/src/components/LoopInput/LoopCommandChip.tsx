import React from "react";
import { Terminal, X } from "lucide-react";
import { useLoopStore } from "../../stores/loopStore";
import styles from "./index.module.less";

/**
 * Atomic command chip shown in the sender prefix area when a loop skill
 * is selected. Supports single-backspace highlight → double-backspace delete.
 */
export const LoopCommandChip: React.FC = () => {
  const { selectedSkill, chipHighlighted, setSelectedSkill } = useLoopStore();

  if (!selectedSkill) return null;

  const cls = [
    styles.loopChip,
    chipHighlighted ? styles.loopChipHighlighted : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cls}>
      <Terminal size={14} style={{ opacity: 0.8, flexShrink: 0 }} />
      <span>/{selectedSkill.name}</span>
      <X
        className={styles.chipClose}
        size={12}
        onClick={(e) => {
          e.stopPropagation();
          setSelectedSkill(null);
        }}
      />
    </div>
  );
};
