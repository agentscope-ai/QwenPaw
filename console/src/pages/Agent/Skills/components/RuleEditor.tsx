import { useState, useEffect, useCallback } from "react";
import { Button, Input, Switch, Empty } from "@agentscope-ai/design";
import { Spin, Space, Typography } from "antd";
import {
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  CheckOutlined,
  CloseOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { api } from "../../../../api";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import type { SkillRule } from "../../../../api/types";
import styles from "./RuleEditor.module.less";

const { Text } = Typography;

interface RuleEditorProps {
  skillName: string;
}

/** Generate a temporary id for locally-added rules. */
function tempId(): string {
  return `temp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function RuleEditor({ skillName }: RuleEditorProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [rules, setRules] = useState<SkillRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Inline editing state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getSkillRules(skillName);
      setRules(res.rules || []);
      setDirty(false);
    } catch {
      message.error(t("skills.rulesLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [skillName, message, t]);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  // --- Local mutations (mark dirty, don't save yet) ---

  const handleAdd = () => {
    const newRule: SkillRule = {
      id: tempId(),
      content: "",
      enabled: true,
    };
    setRules((prev) => [...prev, newRule]);
    setEditingId(newRule.id);
    setEditText("");
    setDirty(true);
  };

  const handleStartEdit = (rule: SkillRule) => {
    setEditingId(rule.id);
    setEditText(rule.content);
  };

  const handleConfirmEdit = () => {
    if (!editingId) return;
    const trimmed = editText.trim();
    if (!trimmed) {
      message.warning(t("skills.ruleContentRequired"));
      return;
    }
    setRules((prev) =>
      prev.map((r) => (r.id === editingId ? { ...r, content: trimmed } : r)),
    );
    setEditingId(null);
    setEditText("");
    setDirty(true);
  };

  const handleCancelEdit = () => {
    // If cancelling an empty newly-added rule, remove it from the list
    if (editingId) {
      const rule = rules.find((r) => r.id === editingId);
      if (rule && !rule.content.trim()) {
        setRules((prev) => prev.filter((r) => r.id !== editingId));
      }
    }
    setEditingId(null);
    setEditText("");
  };

  const handleDelete = (id: string) => {
    setRules((prev) => prev.filter((r) => r.id !== id));
    if (editingId === id) {
      setEditingId(null);
      setEditText("");
    }
    setDirty(true);
  };

  const handleToggleEnabled = (id: string, enabled: boolean) => {
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, enabled } : r)),
    );
    setDirty(true);
  };

  // --- Save to backend ---

  const handleSave = async () => {
    // Validate: no empty content
    const emptyRule = rules.find((r) => !r.content.trim());
    if (emptyRule) {
      message.warning(t("skills.ruleContentRequired"));
      return;
    }

    setSaving(true);
    try {
      const res = await api.updateSkillRules(skillName, rules);
      setRules(res.rules || []);
      setDirty(false);
      message.success(t("skills.rulesSaved"));
    } catch {
      message.error(t("skills.rulesSaveFailed"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className={styles.loading}>
        <Spin size="small" />
      </div>
    );
  }

  return (
    <div className={styles.ruleEditor}>
      <div className={styles.header}>
        <Space>
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={handleAdd}
          >
            {t("skills.addRule")}
          </Button>
          {dirty && (
            <Button
              size="small"
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
            >
              {t("skills.saveRules")}
            </Button>
          )}
          {dirty && !saving && (
            <Button size="small" onClick={loadRules}>
              {t("common.cancel")}
            </Button>
          )}
        </Space>
      </div>

      {rules.length === 0 && editingId === null ? (
        <Empty description={t("skills.noRules")} />
      ) : (
        <div className={styles.ruleList}>
          {rules.map((rule) => (
            <div key={rule.id} className={styles.ruleItem}>
              <div className={styles.ruleSwitch}>
                <Switch
                  size="small"
                  checked={rule.enabled}
                  onChange={(checked) =>
                    handleToggleEnabled(rule.id, checked)
                  }
                />
              </div>
              <div className={styles.ruleContent}>
                {editingId === rule.id ? (
                  <Input.TextArea
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    autoSize={{ minRows: 1, maxRows: 4 }}
                    autoFocus
                    onPressEnter={handleConfirmEdit}
                  />
                ) : (
                  <Text className={rule.enabled ? "" : styles.disabled}>
                    {rule.content || t("skills.emptyRule")}
                  </Text>
                )}
              </div>
              <div className={styles.ruleActions}>
                {editingId === rule.id ? (
                  <Space size="small">
                    <Button
                      size="small"
                      type="link"
                      icon={<CheckOutlined />}
                      onClick={handleConfirmEdit}
                    />
                    <Button
                      size="small"
                      type="link"
                      icon={<CloseOutlined />}
                      onClick={handleCancelEdit}
                    />
                  </Space>
                ) : (
                  <Space size="small">
                    <Button
                      size="small"
                      type="link"
                      icon={<EditOutlined />}
                      onClick={() => handleStartEdit(rule)}
                    />
                    <Button
                      size="small"
                      type="link"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleDelete(rule.id)}
                    />
                  </Space>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
