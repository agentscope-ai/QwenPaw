import React, { useEffect, useRef } from "react";
import type { CommandSuggestion } from "../types";
import styles from "./MessageInput.module.less";

interface CommandSuggestionsProps {
  suggestions: CommandSuggestion[];
  activeIndex?: number;
  onSelect: (cmd: CommandSuggestion) => void;
  onDismiss: () => void;
}

const CommandSuggestions: React.FC<CommandSuggestionsProps> = ({
  suggestions,
  activeIndex = -1,
  onSelect,
  onDismiss,
}) => {
  const activeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <div className={styles.suggestionsPanel} role="listbox">
      {suggestions.map((cmd, index) => (
        <div
          key={cmd.command}
          ref={index === activeIndex ? activeRef : undefined}
          className={`${styles.suggestionItem} ${
            index === activeIndex ? styles.suggestionItemActive : ""
          }`}
          onClick={() => onSelect(cmd)}
          role="option"
          aria-selected={index === activeIndex}
          tabIndex={-1}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSelect(cmd);
            if (e.key === "Escape") onDismiss();
          }}
        >
          <span className={styles.suggestionCommand}>{cmd.command}</span>
          <span className={styles.suggestionDescription}>
            {cmd.description}
          </span>
        </div>
      ))}
    </div>
  );
};

export default CommandSuggestions;
