import {
  Drawer,
  Form,
  Input,
  Switch,
  Button,
  Tag,
} from "@agentscope-ai/design";
import type { ACPHarnessInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { useState, useEffect } from "react";
import styles from "../index.module.less";

interface HarnessEditDrawerProps {
  open: boolean;
  harness: ACPHarnessInfo | null;
  onClose: () => void;
  onSubmit: (
    key: string,
    values: {
      command: string;
      args: string[];
      env: Record<string, string>;
      enabled: boolean;
    },
  ) => Promise<boolean>;
  isCreating?: boolean;
}

export function HarnessEditDrawer({
  open,
  harness,
  onClose,
  onSubmit,
  isCreating = false,
}: HarnessEditDrawerProps) {
  const { t } = useTranslation();
  const [submitting, setSubmitting] = useState(false);
  const [key, setKey] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [env, setEnv] = useState<Record<string, string>>({});
  const [enabled, setEnabled] = useState(false);
  const [newEnvKey, setNewEnvKey] = useState("");
  const [newEnvValue, setNewEnvValue] = useState("");
  const [showNewEnv, setShowNewEnv] = useState(false);

  useEffect(() => {
    if (open && harness) {
      setKey(harness.key);
      setCommand(harness.command || "");
      setArgs(harness.args?.join(" ") || "");
      setEnv(harness.env || {});
      setEnabled(harness.enabled || false);
    } else if (open && isCreating) {
      setKey("");
      setCommand("npx");
      setArgs("");
      setEnv({});
      setEnabled(false);
    }
    setShowNewEnv(false);
    setNewEnvKey("");
    setNewEnvValue("");
  }, [open, harness, isCreating]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const submitKey = isCreating ? key : harness!.key;
      const success = await onSubmit(submitKey, {
        command,
        args: args.split(" ").filter(Boolean),
        env,
        enabled,
      });
      if (success) {
        onClose();
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddEnv = () => {
    if (newEnvKey.trim()) {
      setEnv({ ...env, [newEnvKey.trim()]: newEnvValue });
      setNewEnvKey("");
      setNewEnvValue("");
      setShowNewEnv(false);
    }
  };

  const handleRemoveEnv = (keyToRemove: string) => {
    const { [keyToRemove]: _, ...rest } = env;
    setEnv(rest);
  };

  const title = isCreating ? t("acp.createHarness") : t("acp.editHarness");

  return (
    <Drawer
      title={title}
      placement="right"
      onClose={onClose}
      open={open}
      width={600}
      footer={
        <div
          style={{
            textAlign: "right",
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
          }}
        >
          <Button onClick={onClose} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button type="primary" onClick={handleSubmit} loading={submitting}>
            {isCreating ? t("common.create") : t("common.save")}
          </Button>
        </div>
      }
    >
      <Form layout="vertical">
        {isCreating && (
          <Form.Item
            label={t("acp.harnessKey")}
            required
            extra={t("acp.harnessKeyHelp")}
          >
            <Input
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="opencode"
              disabled={submitting}
            />
          </Form.Item>
        )}

        <Form.Item
          label={t("acp.command")}
          required
          extra={t("acp.commandHelp")}
        >
          <Input
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="npx"
            disabled={submitting}
          />
        </Form.Item>

        <Form.Item label={t("acp.args")} extra={t("acp.argsHelp")}>
          <Input
            value={args}
            onChange={(e) => setArgs(e.target.value)}
            placeholder="-y opencode-ai@latest acp"
            disabled={submitting}
          />
        </Form.Item>

        <Form.Item label={t("acp.enabled")} valuePropName="checked">
          <Switch
            checked={enabled}
            onChange={setEnabled}
            disabled={submitting}
          />
        </Form.Item>

        <Form.Item label={t("acp.envVars")}>
          <div className={styles.envContainer}>
            {Object.entries(env).map(([k]) => (
              <div key={k} className={styles.envRow}>
                <Tag className={styles.envTag}>
                  <span className={styles.envKey}>{k}</span>
                  <span className={styles.envSeparator}>=</span>
                  <span className={styles.envValue}>******</span>
                </Tag>
                <Button
                  type="text"
                  size="small"
                  danger
                  onClick={() => handleRemoveEnv(k)}
                  disabled={submitting}
                >
                  {t("common.delete")}
                </Button>
              </div>
            ))}

            {showNewEnv ? (
              <div className={styles.newEnvRow}>
                <Input
                  placeholder={t("acp.envKeyPlaceholder")}
                  value={newEnvKey}
                  onChange={(e) => setNewEnvKey(e.target.value)}
                  disabled={submitting}
                  style={{ width: 150 }}
                />
                <span>=</span>
                <Input
                  placeholder={t("acp.envValuePlaceholder")}
                  value={newEnvValue}
                  onChange={(e) => setNewEnvValue(e.target.value)}
                  disabled={submitting}
                  style={{ width: 200 }}
                />
                <Button
                  type="primary"
                  size="small"
                  onClick={handleAddEnv}
                  disabled={submitting || !newEnvKey.trim()}
                >
                  {t("common.confirm")}
                </Button>
                <Button
                  size="small"
                  onClick={() => {
                    setShowNewEnv(false);
                    setNewEnvKey("");
                    setNewEnvValue("");
                  }}
                  disabled={submitting}
                >
                  {t("common.cancel")}
                </Button>
              </div>
            ) : (
              <Button
                type="dashed"
                size="small"
                onClick={() => setShowNewEnv(true)}
                disabled={submitting}
              >
                + {t("acp.addEnvVar")}
              </Button>
            )}
          </div>
        </Form.Item>
      </Form>
    </Drawer>
  );
}
