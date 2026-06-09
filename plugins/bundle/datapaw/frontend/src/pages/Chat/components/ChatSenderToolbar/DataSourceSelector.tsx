import { useCallback, useEffect, useMemo, useState, type FC } from "react";
import { Button, Popover, Radio } from "@agentscope-ai/design";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { Database, ChevronDown, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import {
  DATA_SOURCE_OPTIONS,
  DATA_SOURCE_STORAGE_PREFIX,
  type DataSourceId,
} from "./constants";
import { resolveSessionStorageKey } from "./utils";
import styles from "./index.module.less";

function readStoredDataSource(sessionKey: string): DataSourceId {
  try {
    const stored = sessionStorage.getItem(`${DATA_SOURCE_STORAGE_PREFIX}${sessionKey}`);
    if (
      stored &&
      DATA_SOURCE_OPTIONS.some((item) => item.id === stored)
    ) {
      return stored as DataSourceId;
    }
  } catch {
    /* ignore */
  }
  return "stockstar";
}

function writeStoredDataSource(sessionKey: string, value: DataSourceId): void {
  try {
    sessionStorage.setItem(`${DATA_SOURCE_STORAGE_PREFIX}${sessionKey}`, value);
  } catch {
    /* ignore */
  }
}

const DataSourceSelector: FC = () => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { currentSessionId } = useChatAnywhereSessionsState();
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<DataSourceId>("stockstar");

  const sessionKey = useMemo(
    () => resolveSessionStorageKey(currentSessionId),
    [currentSessionId],
  );

  useEffect(() => {
    setSelectedId(readStoredDataSource(sessionKey));
  }, [sessionKey]);

  const handleSelect = useCallback(
    (value: DataSourceId) => {
      setSelectedId(value);
      writeStoredDataSource(sessionKey, value);
      setOpen(false);
    },
    [sessionKey],
  );

  const handleAddSource = useCallback(() => {
    message.info(t("chat.dataSource.addComingSoon"));
  }, [message, t]);

  const content = (
    <div className={styles.panel}>
      <div className={styles.panelTitle}>{t("chat.dataSource.title")}</div>
      <Radio.Group
        value={selectedId}
        onChange={(event) => handleSelect(event.target.value as DataSourceId)}
        className={styles.optionList}
      >
        {DATA_SOURCE_OPTIONS.map((item) => (
          <label key={item.id} className={styles.optionRow} htmlFor={`ds-${item.id}`}>
            <span className={styles.optionLeft}>
              <span
                className={styles.badge}
                style={{ backgroundColor: item.accent }}
                aria-hidden
              >
                {item.badge}
              </span>
              <span className={styles.optionLabel}>{t(item.labelKey)}</span>
            </span>
            <Radio id={`ds-${item.id}`} value={item.id} />
          </label>
        ))}
      </Radio.Group>
      <Button
        type="default"
        className={styles.addButton}
        icon={<Plus size={14} />}
        onClick={handleAddSource}
      >
        {t("chat.dataSource.add")}
      </Button>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      placement="topLeft"
      open={open}
      onOpenChange={setOpen}
    >
      <button
        type="button"
        className={`${styles.trigger} ${open ? styles.triggerOpen : ""}`}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className={styles.triggerIcon}>
          <Database size={14} />
        </span>
        <span>{t("chat.dataSource.label")}</span>
        <span className={styles.triggerChevron}>
          <ChevronDown size={14} />
        </span>
      </button>
    </Popover>
  );
};

export default DataSourceSelector;
