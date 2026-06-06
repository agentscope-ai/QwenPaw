import React, { useEffect, useMemo, useState } from "react";
import { Modal, Checkbox, Button, Space, Typography, message } from "antd";
import { useTranslation } from "react-i18next";
import {
  chatCommandsApi,
  AvailableCommand,
} from "../../../api/modules/chatCommands";

interface Props {
  visible: boolean;
  onClose: () => void;
  selected: string[];
  onChange: (commands: string[]) => void;
}

const CATEGORY_I18N_KEYS: Record<string, string> = {
  context: "chat.commands.category.context",
  history: "chat.commands.category.history",
  model: "chat.commands.category.model",
  session: "chat.commands.category.session",
  control: "chat.commands.category.control",
  daemon: "chat.commands.category.daemon",
};

const CATEGORY_ORDER = [
  "context",
  "history",
  "model",
  "session",
  "control",
  "daemon",
];

export const CommandCustomizer: React.FC<Props> = ({
  visible,
  onClose,
  selected,
  onChange,
}) => {
  const { t } = useTranslation();
  const [available, setAvailable] = useState<AvailableCommand[]>([]);
  const [draft, setDraft] = useState<string[]>(selected);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (visible) {
      setDraft([...selected]);
      chatCommandsApi
        .getAvailable()
        .then(setAvailable)
        .catch(() => {});
    }
  }, [visible]);

  const handleToggle = (cmd: string, checked: boolean) => {
    setDraft((prev) =>
      checked ? [...prev, cmd] : prev.filter((c) => c !== cmd),
    );
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      await chatCommandsApi.update(draft);
      onChange(draft);
      message.success(t("chat.commands.saveSuccess", "保存成功"));
      onClose();
    } catch {
      message.error(t("chat.commands.saveFailed", "保存失败"));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setDraft(["clear", "compact", "mission", "skills"]);
  };

  const grouped = useMemo(() => {
    const map = new Map<string, AvailableCommand[]>();
    for (const cmd of available) {
      if (cmd.command === "plan") continue;
      const arr = map.get(cmd.category) ?? [];
      arr.push(cmd);
      map.set(cmd.category, arr);
    }
    return CATEGORY_ORDER.filter((cat) => map.has(cat)).map((cat) => ({
      category: cat,
      label: t(CATEGORY_I18N_KEYS[cat], cat),
      commands: map.get(cat)!,
    }));
  }, [available, t]);

  return (
    <Modal
      open={visible}
      title={t("chat.commands.customizeTitle", "自定义快捷命令")}
      onCancel={onClose}
      footer={
        <Space>
          <Button onClick={handleReset}>
            {t("chat.commands.resetToDefault", "恢复默认")}
          </Button>
          <Button type="primary" loading={loading} onClick={handleSave}>
            {t("chat.commands.save", "保存")}
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        {t(
          "chat.commands.customizeHint",
          "勾选你希望在输入框 / 菜单中显示的魔法命令",
        )}
      </Typography.Paragraph>
      {grouped.map(({ category, label, commands }) => (
        <div key={category} style={{ marginBottom: 12 }}>
          <Typography.Text strong>{label}</Typography.Text>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "8px 16px",
              marginTop: 4,
            }}
          >
            {commands.map((cmd) => (
              <Checkbox
                key={cmd.command}
                checked={draft.includes(cmd.command)}
                onChange={(e) => handleToggle(cmd.command, e.target.checked)}
              >
                {cmd.display}
              </Checkbox>
            ))}
          </div>
        </div>
      ))}
    </Modal>
  );
};
