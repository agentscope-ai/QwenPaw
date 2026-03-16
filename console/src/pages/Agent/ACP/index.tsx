import { useState } from "react";
import { Button, Empty } from "@agentscope-ai/design";
import { useACP } from "./useACP";
import {
  ACPHarnessCard,
  ACPGlobalSettings,
  HarnessEditDrawer,
} from "./components";
import { useTranslation } from "react-i18next";
import type { ACPHarnessInfo } from "../../../api/types";

function ACPPage() {
  const { t } = useTranslation();
  const {
    harnesses,
    config,
    loading,
    saving,
    toggleHarnessEnabled,
    deleteHarness,
    createHarness,
    updateHarness,
    updateGlobalSettings,
  } = useACP();
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingHarness, setEditingHarness] = useState<ACPHarnessInfo | null>(
    null,
  );
  const [isCreating, setIsCreating] = useState(false);

  const handleToggleEnabled = async (key: string) => {
    await toggleHarnessEnabled(key);
  };

  const handleDelete = async (key: string) => {
    await deleteHarness(key);
  };

  const handleEdit = (harness: ACPHarnessInfo) => {
    setEditingHarness(harness);
    setIsCreating(false);
    setDrawerOpen(true);
  };

  const handleCreate = () => {
    setEditingHarness(null);
    setIsCreating(true);
    setDrawerOpen(true);
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingHarness(null);
    setIsCreating(false);
  };

  const handleSubmit = async (
    key: string,
    values: {
      command: string;
      args: string[];
      env: Record<string, string>;
      enabled: boolean;
    },
  ) => {
    if (isCreating) {
      return await createHarness(key, values);
    } else {
      return await updateHarness(key, values);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 4 }}>
            {t("acp.title")}
          </h1>
          <p style={{ margin: 0, color: "#999", fontSize: 14 }}>
            {t("acp.description")}
          </p>
        </div>
        <Button type="primary" onClick={handleCreate}>
          {t("acp.createHarness")}
        </Button>
      </div>

      <ACPGlobalSettings
        config={config}
        onUpdate={updateGlobalSettings}
        saving={saving}
      />

      <div style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>
          {t("acp.harnesses")}
        </h2>

        {loading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <p style={{ color: "#999" }}>{t("common.loading")}</p>
          </div>
        ) : harnesses.length === 0 ? (
          <Empty description={t("acp.emptyState")} />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
              gap: 20,
            }}
          >
            {harnesses.map((harness) => (
              <ACPHarnessCard
                key={harness.key}
                harness={harness}
                onToggle={handleToggleEnabled}
                onDelete={handleDelete}
                onEdit={handleEdit}
                isHovered={hoverKey === harness.key}
                onMouseEnter={() => setHoverKey(harness.key)}
                onMouseLeave={() => setHoverKey(null)}
              />
            ))}
          </div>
        )}
      </div>

      <HarnessEditDrawer
        open={drawerOpen}
        harness={editingHarness}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
        isCreating={isCreating}
      />
    </div>
  );
}

export default ACPPage;
