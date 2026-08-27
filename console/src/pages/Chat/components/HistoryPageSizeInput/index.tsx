import { InputNumber } from "antd";
import React, {
  useCallback,
  useEffect,
  useState,
  useSyncExternalStore,
} from "react";
import { useTranslation } from "react-i18next";
import {
  DEFAULT_HISTORY_PAGE_SIZE,
  HISTORY_PAGE_SIZE_MAX,
  HISTORY_PAGE_SIZE_MIN,
  commitHistoryPageSize,
  getHistoryPageSize,
  subscribeHistoryPageSize,
} from "../../sessionApi/historyPageSize";

export interface HistoryPageSizeInputProps {
  compact?: boolean;
  disabled?: boolean;
  onCommitted?: (value: number) => void | Promise<void>;
}

const HistoryPageSizeInput: React.FC<HistoryPageSizeInputProps> = ({
  compact = false,
  disabled = false,
  onCommitted,
}) => {
  const { t } = useTranslation();
  const stored = useSyncExternalStore(
    subscribeHistoryPageSize,
    getHistoryPageSize,
    () => DEFAULT_HISTORY_PAGE_SIZE,
  );
  const [draft, setDraft] = useState<number | null>(stored);

  useEffect(() => {
    setDraft(stored);
  }, [stored]);

  const commit = useCallback(async () => {
    const result = commitHistoryPageSize(draft);
    if (result === null) {
      setDraft(getHistoryPageSize());
      return;
    }
    setDraft(result.value);
    if (result.changed) await onCommitted?.(result.value);
  }, [draft, onCommitted]);

  const input = (
    <span
      data-testid={compact ? "history-page-size" : "settings-history-page-size"}
    >
      <InputNumber
        min={HISTORY_PAGE_SIZE_MIN}
        max={HISTORY_PAGE_SIZE_MAX}
        value={draft}
        disabled={disabled}
        onChange={(value) => setDraft(typeof value === "number" ? value : null)}
        onBlur={() => {
          void commit();
        }}
        onPressEnter={() => {
          void commit();
        }}
        style={{ width: compact ? 88 : 140 }}
        size={compact ? "small" : "middle"}
        aria-label={t(
          "chat.historyPageSizeAria",
          "Messages loaded when opening a chat",
        )}
      />
    </span>
  );

  if (compact) return input;

  return (
    <div>
      <div style={{ marginBottom: 8, fontWeight: 500 }}>
        {t(
          "consoleSettings.historyPageSize",
          "Messages loaded when opening a chat",
        )}
      </div>
      <div style={{ marginBottom: 12, color: "var(--color-text-secondary)" }}>
        {t(
          "consoleSettings.historyPageSizeHint",
          "How many of the most recent messages to fetch when a chat is opened or when loading earlier messages. Range 1–10000.",
        )}
      </div>
      {input}
    </div>
  );
};

export default HistoryPageSizeInput;
