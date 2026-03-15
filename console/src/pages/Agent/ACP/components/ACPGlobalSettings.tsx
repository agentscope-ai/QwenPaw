import { Card, Form, Switch, Input, Button } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import type { ACPConfig } from "../../../../api/types";
import styles from "../index.module.less";

interface ACPGlobalSettingsProps {
  config: ACPConfig | null;
  onUpdate: (settings: {
    enabled?: boolean;
    require_approval?: boolean;
    save_dir?: string;
  }) => Promise<boolean>;
  saving: boolean;
}

export function ACPGlobalSettings({
  config,
  onUpdate,
  saving,
}: ACPGlobalSettingsProps) {
  const { t } = useTranslation();
  const [localEnabled, setLocalEnabled] = useState(false);
  const [localRequireApproval, setLocalRequireApproval] = useState(false);
  const [localSaveDir, setLocalSaveDir] = useState("");
  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    if (config) {
      setLocalEnabled(config.enabled);
      setLocalRequireApproval(config.require_approval);
      setLocalSaveDir(config.save_dir);
      setHasChanges(false);
    }
  }, [config]);

  const handleEnabledChange = (checked: boolean) => {
    setLocalEnabled(checked);
    setHasChanges(true);
  };

  const handleRequireApprovalChange = (checked: boolean) => {
    setLocalRequireApproval(checked);
    setHasChanges(true);
  };

  const handleSaveDirChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setLocalSaveDir(e.target.value);
    setHasChanges(true);
  };

  const handleSave = async () => {
    const success = await onUpdate({
      enabled: localEnabled,
      require_approval: localRequireApproval,
      save_dir: localSaveDir,
    });
    if (success) {
      setHasChanges(false);
    }
  };

  const handleReset = () => {
    if (config) {
      setLocalEnabled(config.enabled);
      setLocalRequireApproval(config.require_approval);
      setLocalSaveDir(config.save_dir);
      setHasChanges(false);
    }
  };

  return (
    <Card
      title={t("acp.globalSettings")}
      className={styles.globalSettingsCard}
    >
      <Form layout="vertical">
        <Form.Item
          label={t("acp.enabled")}
          extra={t("acp.enabledDescription")}
        >
          <Switch
            checked={localEnabled}
            onChange={handleEnabledChange}
            disabled={saving}
          />
        </Form.Item>

        <Form.Item
          label={t("acp.requireApproval")}
          extra={t("acp.requireApprovalDescription")}
        >
          <Switch
            checked={localRequireApproval}
            onChange={handleRequireApprovalChange}
            disabled={saving || !localEnabled}
          />
        </Form.Item>

        <Form.Item
          label={t("acp.saveDir")}
          extra={t("acp.saveDirDescription")}
        >
          <Input
            value={localSaveDir}
            onChange={handleSaveDirChange}
            disabled={saving || !localEnabled}
            placeholder="~/.copaw/acp_sessions"
          />
        </Form.Item>

        {hasChanges && (
          <Form.Item>
            <div style={{ display: "flex", gap: 8 }}>
              <Button
                type="primary"
                onClick={handleSave}
                loading={saving}
              >
                {t("common.save")}
              </Button>
              <Button onClick={handleReset} disabled={saving}>
                {t("common.reset")}
              </Button>
            </div>
          </Form.Item>
        )}
      </Form>
    </Card>
  );
}
