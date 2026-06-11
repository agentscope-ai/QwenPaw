import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
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
  conflictRenameModal: React.ReactNode;
} {
  const { t } = useTranslation();
  const [items, setItems] = useState<InternalItem[]>([]);
  const [resolver, setResolver] = useState<
    ((result: Record<string, string> | null) => void) | null
  >(null);

  const showConflictRenameModal = (
    incoming: ConflictItem[],
  ): Promise<Record<string, string> | null> =>
    new Promise((resolve) => {
      setItems(
        incoming.map((item) => ({ ...item, new_name: item.suggested_name })),
      );
      setResolver(() => resolve);
    });

  const handleOk = () => {
    const renameMap: Record<string, string> = {};
    for (const item of items) {
      if (item.new_name.trim()) {
        renameMap[item.key] = item.new_name.trim();
      }
    }
    resolver?.(renameMap);
    setItems([]);
    setResolver(null);
  };

  const handleCancel = () => {
    resolver?.(null);
    setItems([]);
    setResolver(null);
  };

  const conflictRenameModal = (
    <Dialog open={items.length > 0} onOpenChange={(o) => !o && handleCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("skillPool.multiConflictTitle")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("skillPool.multiConflictTitle")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {t("skillPool.multiConflictDesc")}
          </p>
          {items.map((item, i) => (
            <div key={item.key} className="space-y-1">
              <div className="text-xs text-muted-foreground">
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
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={handleCancel}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleOk}>{t("common.confirm")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );

  return { showConflictRenameModal, conflictRenameModal };
}
