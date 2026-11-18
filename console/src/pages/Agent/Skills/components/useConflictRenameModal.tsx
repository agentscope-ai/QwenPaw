import { useCallback, useRef, useState } from "react";
import { Input, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

export interface ConflictItem {
  key: string;
  label: string;
  suggested_name: string;
}

interface InternalItem extends ConflictItem {
  new_name: string;
}

export function useConflictRenameModal(): {
  showConflictRenameModal: (
    items: ConflictItem[],
  ) => Promise<Record<string, string> | null>;
  cancelConflictRenameModal: () => void;
  conflictRenameModal: React.ReactNode;
} {
  const { t } = useTranslation();
  const [items, setItems] = useState<InternalItem[]>([]);
  const resolverRef = useRef<
    ((result: Record<string, string> | null) => void) | null
  >(null);

  const cancelConflictRenameModal = useCallback(() => {
    const resolve = resolverRef.current;
    resolverRef.current = null;
    setItems([]);
    resolve?.(null);
  }, []);

  const showConflictRenameModal = (
    incoming: ConflictItem[],
  ): Promise<Record<string, string> | null> =>
    new Promise((resolve) => {
      resolverRef.current?.(null);
      setItems(
        incoming.map((item) => ({ ...item, new_name: item.suggested_name })),
      );
      resolverRef.current = resolve;
    });

  const handleOk = () => {
    const renameMap: Record<string, string> = {};
    for (const item of items) {
      if (item.new_name.trim()) {
        renameMap[item.key] = item.new_name.trim();
      }
    }
    const resolve = resolverRef.current;
    resolverRef.current = null;
    setItems([]);
    resolve?.(renameMap);
  };

  const conflictRenameModal = (
    <Modal
      open={items.length > 0}
      title={t("skillPool.multiConflictTitle")}
      onOk={handleOk}
      onCancel={cancelConflictRenameModal}
      zIndex={2100}
    >
      <p>{t("skillPool.multiConflictDesc")}</p>
      {items.map((item, i) => (
        <div key={item.key} style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 4 }}>
            {t("skillPool.renameEntry", { name: item.label })}
          </div>
          <Input
            value={item.new_name}
            onChange={(e) => {
              const next = [...items];
              next[i] = { ...next[i], new_name: e.target.value };
              setItems(next);
            }}
          />
        </div>
      ))}
    </Modal>
  );

  return {
    showConflictRenameModal,
    cancelConflictRenameModal,
    conflictRenameModal,
  };
}
