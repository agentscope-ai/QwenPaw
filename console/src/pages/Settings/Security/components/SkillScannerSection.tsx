import { useState, useCallback } from "react";
import {
  Card,
  InputNumber,
  Table,
  Tag,
  Button,
  Modal,
  message,
  Tooltip,
  Empty,
} from "@agentscope-ai/design";
import { Select, Space } from "antd";
import { Trash2, ShieldCheck, Eye, ShieldOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSkillScanner } from "../useSkillScanner";
import type {
  BlockedSkillRecord,
  BlockedSkillFinding,
  SkillScannerWhitelistEntry,
  SkillScannerMode,
} from "../../../../api/modules/security";
import { skillApi } from "../../../../api/modules/skill";
import styles from "../index.module.less";

function FindingsModal({
  findings,
  skillName,
  open,
  onClose,
}: {
  findings: BlockedSkillFinding[];
  skillName: string;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  return (
    <Modal
      title={`${t(
        "security.skillScanner.scanAlerts.viewFindings",
      )} - ${skillName}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
    >
      <Table
        dataSource={findings}
        rowKey={(_, idx) => String(idx)}
        pagination={false}
        size="small"
        columns={[
          {
            title: "Title",
            dataIndex: "title",
            key: "title",
            width: 200,
          },
          {
            title: "File",
            key: "location",
            width: 160,
            render: (_: unknown, record: BlockedSkillFinding) =>
              record.line_number
                ? `${record.file_path}:${record.line_number}`
                : record.file_path,
          },
          {
            title: "Description",
            dataIndex: "description",
            key: "description",
            ellipsis: true,
          },
        ]}
      />
    </Modal>
  );
}

export function SkillScannerSection() {
  const { t } = useTranslation();
  const {
    config,
    blockedHistory,
    whitelist,
    loading,
    updateConfig,
    addToWhitelist,
    removeFromWhitelist,
    removeBlockedEntry,
    clearBlockedHistory,
  } = useSkillScanner();

  const [saving, setSaving] = useState(false);
  const [findingsModal, setFindingsModal] = useState<{
    open: boolean;
    findings: BlockedSkillFinding[];
    skillName: string;
  }>({ open: false, findings: [], skillName: "" });

  const handleModeChange = useCallback(
    async (mode: SkillScannerMode) => {
      setSaving(true);
      const ok = await updateConfig({ mode });
      if (ok) message.success(t("security.skillScanner.saveSuccess"));
      else message.error(t("security.skillScanner.saveFailed"));
      setSaving(false);
    },
    [updateConfig, t],
  );

  const [pendingTimeout, setPendingTimeout] = useState<number | null>(null);

  const handleTimeoutBlur = useCallback(async () => {
    const value = pendingTimeout;
    if (value === null || value < 5 || value > 300) {
      setPendingTimeout(null);
      return;
    }
    setSaving(true);
    const ok = await updateConfig({ timeout: value });
    if (ok) message.success(t("security.skillScanner.saveSuccess"));
    else message.error(t("security.skillScanner.saveFailed"));
    setPendingTimeout(null);
    setSaving(false);
  }, [pendingTimeout, updateConfig, t]);

  const handleAllowSkill = useCallback(
    async (record: BlockedSkillRecord, index: number) => {
      const ok = await addToWhitelist(record.skill_name, record.content_hash);
      if (ok) {
        message.success(t("security.skillScanner.whitelist.addSuccess"));
        await removeBlockedEntry(index);
      } else {
        message.error(t("security.skillScanner.whitelist.addFailed"));
      }
    },
    [addToWhitelist, removeBlockedEntry, t],
  );

  const handleRemoveWhitelist = useCallback(
    async (skillName: string) => {
      Modal.confirm({
        title: t("security.skillScanner.whitelist.removeConfirm"),
        content: t("security.skillScanner.whitelist.removeWillDisable"),
        onOk: async () => {
          const ok = await removeFromWhitelist(skillName);
          if (!ok) {
            message.error(t("security.skillScanner.whitelist.removeFailed"));
            return;
          }
          try {
            await skillApi.disableSkill(skillName);
            message.success(
              t("security.skillScanner.whitelist.removeAndDisabled"),
            );
          } catch {
            message.success(t("security.skillScanner.whitelist.removeSuccess"));
          }
        },
      });
    },
    [removeFromWhitelist, t],
  );

  const handleClearHistory = useCallback(() => {
    Modal.confirm({
      title: t("security.skillScanner.scanAlerts.clearConfirm"),
      onOk: async () => {
        await clearBlockedHistory();
      },
    });
  }, [clearBlockedHistory, t]);

  if (loading || !config) return null;

  const enabled = config.mode !== "off";

  const blockedColumns = [
    {
      title: t("security.skillScanner.scanAlerts.skillName"),
      dataIndex: "skill_name",
      key: "skill_name",
      width: 180,
    },
    {
      title: t("security.skillScanner.scanAlerts.action"),
      dataIndex: "action",
      key: "action",
      width: 100,
      render: (action: string) => (
        <Tag color={action === "blocked" ? "red" : "orange"}>
          {action === "blocked"
            ? t("security.skillScanner.scanAlerts.actionBlocked")
            : t("security.skillScanner.scanAlerts.actionWarned")}
        </Tag>
      ),
    },
    {
      title: t("security.skillScanner.scanAlerts.time"),
      dataIndex: "blocked_at",
      key: "blocked_at",
      width: 180,
      render: (val: string) => {
        try {
          return new Date(val).toLocaleString();
        } catch {
          return val;
        }
      },
    },
    {
      title: t("security.skillScanner.scanAlerts.actions"),
      key: "actions",
      width: 200,
      render: (_: unknown, record: BlockedSkillRecord, index: number) => (
        <Space size="small">
          <Tooltip title={t("security.skillScanner.scanAlerts.viewFindings")}>
            <Button
              type="text"
              size="small"
              icon={<Eye size={14} />}
              onClick={() =>
                setFindingsModal({
                  open: true,
                  findings: record.findings,
                  skillName: record.skill_name,
                })
              }
            />
          </Tooltip>
          <Tooltip title={t("security.skillScanner.scanAlerts.allowSkill")}>
            <Button
              type="text"
              size="small"
              icon={<ShieldCheck size={14} />}
              onClick={() => handleAllowSkill(record, index)}
            />
          </Tooltip>
          <Tooltip title={t("security.skillScanner.scanAlerts.remove")}>
            <Button
              type="text"
              size="small"
              danger
              icon={<Trash2 size={14} />}
              onClick={() => removeBlockedEntry(index)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  const whitelistColumns = [
    {
      title: t("security.skillScanner.whitelist.skillName"),
      dataIndex: "skill_name",
      key: "skill_name",
      width: 200,
    },
    {
      title: t("security.skillScanner.whitelist.contentHash"),
      dataIndex: "content_hash",
      key: "content_hash",
      width: 200,
      ellipsis: true,
      render: (hash: string) =>
        hash ? (
          <Tooltip title={hash}>
            <code style={{ fontSize: 12 }}>{hash.substring(0, 16)}...</code>
          </Tooltip>
        ) : (
          <span style={{ color: "#999" }}>any</span>
        ),
    },
    {
      title: t("security.skillScanner.whitelist.addedAt"),
      dataIndex: "added_at",
      key: "added_at",
      width: 180,
      render: (val: string) => {
        try {
          return new Date(val).toLocaleString();
        } catch {
          return val;
        }
      },
    },
    {
      title: t("security.skillScanner.whitelist.actions"),
      key: "actions",
      width: 100,
      render: (_: unknown, record: SkillScannerWhitelistEntry) => (
        <Tooltip title={t("security.skillScanner.whitelist.remove")}>
          <Button
            type="text"
            size="small"
            danger
            icon={<ShieldOff size={14} />}
            onClick={() => handleRemoveWhitelist(record.skill_name)}
          />
        </Tooltip>
      ),
    },
  ];

  return (
    <>
      <div className={styles.sectionHeader} style={{ marginTop: 40 }}>
        <div>
          <h2 className={styles.sectionTitle}>
            {t("security.skillScanner.title")}
          </h2>
          <p className={styles.description} style={{ marginTop: 4 }}>
            {t("security.skillScanner.description")}
          </p>
        </div>
      </div>

      <Card className={styles.formCard}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Tooltip title={t("security.skillScanner.modeTooltip")}>
              <span style={{ fontWeight: 500 }}>
                {t("security.skillScanner.mode")}
              </span>
            </Tooltip>
            <Select
              value={config.mode}
              onChange={handleModeChange}
              disabled={saving}
              style={{ width: 140 }}
              options={[
                {
                  value: "block",
                  label: t("security.skillScanner.modeBlock"),
                },
                { value: "warn", label: t("security.skillScanner.modeWarn") },
                { value: "off", label: t("security.skillScanner.modeOff") },
              ]}
            />
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Tooltip title={t("security.skillScanner.timeoutTooltip")}>
              <span style={{ fontWeight: 500 }}>
                {t("security.skillScanner.timeout")}
              </span>
            </Tooltip>
            <InputNumber
              min={5}
              max={300}
              value={pendingTimeout ?? config.timeout}
              onChange={(v) => setPendingTimeout(v)}
              onBlur={handleTimeoutBlur}
              onPressEnter={handleTimeoutBlur}
              disabled={!enabled}
              style={{ width: 100 }}
            />
          </div>
        </div>
      </Card>

      {/* Scan Alerts */}
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>
          {t("security.skillScanner.scanAlerts.title")}
        </h2>
        {blockedHistory.length > 0 && (
          <Button size="small" danger onClick={handleClearHistory}>
            {t("security.skillScanner.scanAlerts.clearAll")}
          </Button>
        )}
      </div>

      <Card className={styles.tableCard}>
        {blockedHistory.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Empty description={t("security.skillScanner.scanAlerts.empty")} />
          </div>
        ) : (
          <Table
            dataSource={blockedHistory}
            columns={blockedColumns}
            rowKey={(_, idx) => String(idx)}
            pagination={false}
            size="small"
          />
        )}
      </Card>

      {/* Whitelist */}
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>
          {t("security.skillScanner.whitelist.title")}
        </h2>
      </div>

      <Card className={styles.tableCard}>
        {whitelist.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Empty description={t("security.skillScanner.whitelist.empty")} />
          </div>
        ) : (
          <Table
            dataSource={whitelist}
            columns={whitelistColumns}
            rowKey="skill_name"
            pagination={false}
            size="small"
          />
        )}
      </Card>

      <FindingsModal
        findings={findingsModal.findings}
        skillName={findingsModal.skillName}
        open={findingsModal.open}
        onClose={() =>
          setFindingsModal({ open: false, findings: [], skillName: "" })
        }
      />
    </>
  );
}
