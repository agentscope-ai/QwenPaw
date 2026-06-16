import { useCallback, useEffect, useMemo, useState, type FC } from "react";
import { Button, Popover, Radio } from "@agentscope-ai/design";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { Database, ChevronDown, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { DATA_CONNECTION_TYPE_META } from "@/pages/Datapaw/DataConnection/types";
import { navigateDataConnection } from "@/pages/Datapaw/DataConnection/navigation";
import { useDataConnections } from "@/pages/Datapaw/DataConnection/useDataConnections";
import {
  resolveSelectedDataSourceId,
  writeSelectedDataSourceId,
} from "./dataSourceSelection";
import { resolveSessionStorageKey } from "./utils";

import styles from "./index.module.less";

const DataSourceSelector: FC = () => {
  const { t } = useTranslation();
  const { currentSessionId } = useChatAnywhereSessionsState();
  const { connections, loading, refresh } = useDataConnections();
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string>("");

  const sessionKey = useMemo(
    () => resolveSessionStorageKey(currentSessionId),
    [currentSessionId],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (loading) return;

    const connectionIds = connections.map((item) => item.id);
    const nextId = resolveSelectedDataSourceId(sessionKey, connectionIds);
    setSelectedId(nextId ?? "");

    if (nextId) {
      writeSelectedDataSourceId(sessionKey, nextId);
    }
  }, [connections, loading, sessionKey]);

  const selectedConnection = useMemo(
    () => connections.find((item) => item.id === selectedId),
    [connections, selectedId],
  );

  const handleSelect = useCallback(
    (value: string) => {
      setSelectedId(value);
      writeSelectedDataSourceId(sessionKey, value);
      setOpen(false);
    },
    [sessionKey],
  );

  const handleAddSource = useCallback(() => {
    setOpen(false);
    navigateDataConnection();
  }, []);

  const content = (
    <div className={styles.panel}>
      <div className={styles.panelTitle}>{t("chat.dataSource.title")}</div>
      {loading ? (
        <div className={styles.emptyHint}>{t("common.loading")}</div>
      ) : connections.length === 0 ? (
        <div className={styles.emptyHint}>{t("chat.dataSource.empty")}</div>
      ) : (
        <Radio.Group
          value={selectedId}
          onChange={(event) => handleSelect(event.target.value)}
          className={styles.optionList}
        >
          {connections.map((item) => {
            const meta = DATA_CONNECTION_TYPE_META[item.type];
            return (
              <label
                key={item.id}
                className={styles.optionRow}
                htmlFor={`ds-${item.id}`}
              >
                <span className={styles.optionLeft}>
                  <span className={styles.optionLabel}>{item.name}</span>
                </span>
                <Radio id={`ds-${item.id}`} value={item.id} />
              </label>
            );
          })}
        </Radio.Group>
      )}
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
        <span>
          {selectedConnection?.type ?? t("chat.dataSource.label")}
        </span>
        <span className={styles.triggerChevron}>
          <ChevronDown size={14} />
        </span>
      </button>
    </Popover>
  );
};

export default DataSourceSelector;
