import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Descriptions,
  Drawer,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Spin,
  Switch,
  Tag,
  Tooltip,
} from "antd";
import {
  Camera,
  Copy,
  MoreHorizontal,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { checkpointsApi } from "@/api/modules/checkpoints";
import type {
  CheckpointGcSettings,
  CheckpointGraphResponse,
  CheckpointNode,
  CheckpointStatus,
} from "@/api/types/checkpoints";
import { useAgentStore } from "@/stores/agentStore";
import { useAppMessage } from "@/hooks/useAppMessage";
import { buildGraphRows, graphLaneCount } from "./graphLayout";
import { CheckpointGraph } from "./CheckpointGraph";
import { RestoreModal } from "./RestoreModal";
import styles from "./index.module.less";

const EMPTY_SUMMARY: CheckpointGraphResponse["summary"] = {
  total: 0,
  auto: 0,
  snapshots: 0,
  safety: 0,
  heads: 0,
};

export default function CheckpointsPage() {
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const [modal, modalContext] = Modal.useModal();
  const [status, setStatus] = useState<CheckpointStatus | null>(null);
  const [graph, setGraph] = useState<CheckpointGraphResponse>({
    nodes: [],
    sessions: [],
    summary: EMPTY_SUMMARY,
    truncated: false,
  });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoSaving, setAutoSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [session, setSession] = useState("all");
  const [selected, setSelected] = useState<CheckpointNode | null>(null);
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [snapshotOpen, setSnapshotOpen] = useState(false);
  const [snapshotName, setSnapshotName] = useState("");
  const [snapshotSession, setSnapshotSession] = useState("");
  const [snapshotSaving, setSnapshotSaving] = useState(false);
  const [gcSettingsOpen, setGcSettingsOpen] = useState(false);
  const [gcSettingsLoading, setGcSettingsLoading] = useState(false);
  const [gcSettingsSaving, setGcSettingsSaving] = useState(false);
  const [gcSettingsForm] = Form.useForm<CheckpointGcSettings>();
  const loadVersion = useRef(0);

  const load = useCallback(async (quiet = false, signal?: AbortSignal) => {
    const version = ++loadVersion.current;
    if (quiet) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const [nextStatus, nextGraph] = await Promise.all([
        checkpointsApi.status(signal),
        checkpointsApi.graph(500, signal),
      ]);
      if (version !== loadVersion.current) return;
      setStatus(nextStatus);
      setGraph(nextGraph);
      setSelected((current) =>
        current
          ? nextGraph.nodes.find((node) => node.commit === current.commit) ??
            null
          : null,
      );
    } catch (caught) {
      if (
        version === loadVersion.current &&
        (caught as Error).name !== "AbortError"
      )
        setError((caught as Error).message);
    } finally {
      if (version === loadVersion.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setStatus(null);
    setGraph({
      nodes: [],
      sessions: [],
      summary: EMPTY_SUMMARY,
      truncated: false,
    });
    setSelected(null);
    setSession("all");
    setSnapshotSession("");
    void load(false, controller.signal);
    return () => controller.abort();
  }, [selectedAgent, load]);

  const sessions = graph.sessions;

  useEffect(() => {
    const first = sessions.find((item) => item.session_id);
    if (!snapshotSession && first) setSnapshotSession(first.session_key);
  }, [sessions, snapshotSession]);

  const filteredNodes = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase(i18n.resolvedLanguage);
    return graph.nodes.filter((node) => {
      if (kind !== "all" && node.kind !== kind) return false;
      if (session !== "all" && node.session_key !== session) return false;
      if (!needle) return true;
      return [
        node.query,
        node.name,
        node.subject,
        node.commit,
        node.session_title,
        node.session_id,
      ]
        .filter(Boolean)
        .some((value) =>
          String(value)
            .toLocaleLowerCase(i18n.resolvedLanguage)
            .includes(needle),
        );
    });
  }, [graph.nodes, search, kind, session, i18n.resolvedLanguage]);

  const rows = useMemo(() => buildGraphRows(filteredNodes), [filteredNodes]);
  const laneCount = useMemo(() => graphLaneCount(rows), [rows]);

  const toggleAuto = async (enabled: boolean) => {
    setAutoSaving(true);
    try {
      const result = await checkpointsApi.setAuto(enabled);
      setStatus((current) =>
        current ? { ...current, auto_enabled: result.auto_enabled } : current,
      );
      message.success(
        enabled ? t("checkpoints.autoEnabled") : t("checkpoints.autoDisabled"),
      );
    } catch (caught) {
      message.error((caught as Error).message);
    } finally {
      setAutoSaving(false);
    }
  };

  const createSnapshot = async () => {
    const target = sessions.find(
      (item) => item.session_key === snapshotSession,
    );
    if (!target) return;
    setSnapshotSaving(true);
    try {
      await checkpointsApi.snapshot({
        session_id: target.session_id,
        user_id: target.user_id,
        channel: target.channel,
        name: snapshotName.trim(),
      });
      setSnapshotOpen(false);
      setSnapshotName("");
      message.success(t("checkpoints.snapshotCreated"));
      await load(true);
    } catch (caught) {
      message.error((caught as Error).message);
    } finally {
      setSnapshotSaving(false);
    }
  };

  const runGc = async (compact = false) => {
    const body = compact ? { compact: true } : {};
    const titleKey = compact
      ? "checkpoints.gc.thoroughTitle"
      : "checkpoints.gc.title";
    const descriptionKey = compact
      ? "checkpoints.gc.thoroughDescription"
      : "checkpoints.gc.description";
    const confirmKey = compact
      ? "checkpoints.gc.thoroughConfirm"
      : "checkpoints.gc.confirm";
    const successKey = compact
      ? "checkpoints.gc.thoroughSuccess"
      : "checkpoints.gc.success";
    try {
      const preview = await checkpointsApi.previewGc(body);
      modal.confirm({
        title: t(titleKey),
        content: t(descriptionKey, {
          count: preview.deleted_refs.length,
        }),
        okText: t(confirmKey),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        onOk: async () => {
          const result = await checkpointsApi.gc(body);
          message.success(t(successKey, { count: result.deleted_refs.length }));
          await load(true);
        },
      });
    } catch (caught) {
      message.error((caught as Error).message);
    }
  };

  const openGcSettings = async () => {
    setGcSettingsOpen(true);
    setGcSettingsLoading(true);
    try {
      const settings = await checkpointsApi.getGcSettings();
      gcSettingsForm.setFieldsValue(settings);
    } catch (caught) {
      setGcSettingsOpen(false);
      message.error((caught as Error).message);
    } finally {
      setGcSettingsLoading(false);
    }
  };

  const saveGcSettings = async () => {
    let values: CheckpointGcSettings;
    try {
      values = await gcSettingsForm.validateFields();
    } catch {
      return;
    }
    setGcSettingsSaving(true);
    try {
      const saved = await checkpointsApi.updateGcSettings(values);
      gcSettingsForm.setFieldsValue(saved);
      setGcSettingsOpen(false);
      message.success(t("checkpoints.gc.settingsSaved"));
    } catch (caught) {
      message.error((caught as Error).message);
    } finally {
      setGcSettingsSaving(false);
    }
  };

  const reset = () =>
    modal.confirm({
      title: t("checkpoints.reset.title"),
      content: t("checkpoints.reset.description"),
      okText: t("checkpoints.reset.confirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        await checkpointsApi.reset();
        setSelected(null);
        message.success(t("checkpoints.reset.success"));
        await load(true);
      },
    });

  const openRestore = () => {
    setRestoreOpen(true);
  };

  return (
    <div className={styles.page}>
      {modalContext}
      <PageHeader
        className={styles.pageHeader}
        items={[{ title: t("nav.agent") }, { title: t("checkpoints.title") }]}
        afterBreadcrumb={
          status?.workspace_dir ? (
            <span className={styles.workspacePath}>{status.workspace_dir}</span>
          ) : null
        }
        extra={
          <div className={styles.headerActions}>
            <label className={styles.autoControl}>
              <span>{t("checkpoints.auto")}</span>
              <Switch
                size="small"
                checked={status?.auto_enabled ?? false}
                loading={autoSaving}
                disabled={!status || loading}
                onChange={toggleAuto}
              />
            </label>
            <Tooltip title={t("checkpoints.refresh")}>
              <Button
                aria-label={t("checkpoints.refresh")}
                icon={<RefreshCw size={16} />}
                loading={refreshing}
                onClick={() => void load(true)}
              />
            </Tooltip>
            <Button
              type="primary"
              icon={<Camera size={16} />}
              disabled={!sessions.some((item) => item.session_id)}
              onClick={() => setSnapshotOpen(true)}
            >
              {t("checkpoints.snapshot")}
            </Button>
            <Dropdown
              trigger={["click"]}
              menu={{
                items: [
                  {
                    key: "gc",
                    icon: <Trash2 size={15} />,
                    label: t("checkpoints.gc.action"),
                    onClick: () => void runGc(),
                  },
                  {
                    key: "compact-gc",
                    danger: true,
                    icon: <Trash2 size={15} />,
                    label: t("checkpoints.gc.thoroughAction"),
                    onClick: () => void runGc(true),
                  },
                  {
                    key: "gc-settings",
                    icon: <Settings2 size={15} />,
                    label: t("checkpoints.gc.settingsAction"),
                    onClick: () => void openGcSettings(),
                  },
                  { type: "divider" },
                  {
                    key: "reset",
                    danger: true,
                    icon: <RotateCcw size={15} />,
                    label: t("checkpoints.reset.action"),
                    onClick: reset,
                  },
                ],
              }}
            >
              <Button
                aria-label={t("checkpoints.more")}
                icon={<MoreHorizontal size={17} />}
              />
            </Dropdown>
          </div>
        }
      />

      <div className={styles.content}>
        <div className={styles.summaryBar}>
          <span>
            <strong>{graph.summary.total}</strong>{" "}
            {t("checkpoints.summary.total")}
          </span>
          <span>
            <i className={styles.autoDot} />
            {graph.summary.auto} {t("checkpoints.kind.auto")}
          </span>
          <span>
            <i className={styles.snapshotDot} />
            {graph.summary.snapshots} {t("checkpoints.kind.snapshot")}
          </span>
          <span>
            <i className={styles.safetyDot} />
            {graph.summary.safety} {t("checkpoints.kind.safety")}
          </span>
          {graph.truncated && (
            <Tag bordered={false}>
              {t("checkpoints.showingLatest", { count: graph.nodes.length })}
            </Tag>
          )}
        </div>

        <div className={styles.toolbar}>
          <Input
            allowClear
            prefix={<Search size={15} />}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("checkpoints.search")}
            className={styles.searchInput}
          />
          <Select
            value={kind}
            onChange={setKind}
            options={[
              { value: "all", label: t("checkpoints.allTypes") },
              { value: "auto", label: t("checkpoints.kind.auto") },
              { value: "snap", label: t("checkpoints.kind.snapshot") },
              { value: "pre-restore", label: t("checkpoints.kind.safety") },
            ]}
          />
          <Select
            value={session}
            onChange={setSession}
            className={styles.sessionFilter}
            options={[
              { value: "all", label: t("checkpoints.allSessions") },
              ...sessions.map((item) => ({
                value: item.session_key,
                label: item.title || item.session_id || item.session_key,
              })),
            ]}
          />
        </div>

        <div className={styles.mainArea}>
          {loading ? (
            <div className={styles.centerState}>
              <Spin />
            </div>
          ) : error ? (
            <div className={styles.centerState}>
              <p>{t("checkpoints.loadFailed")}</p>
              <Button onClick={() => void load()}>
                {t("checkpoints.retry")}
              </Button>
            </div>
          ) : (
            <CheckpointGraph
              rows={rows}
              laneCount={laneCount}
              selectedCommit={selected?.commit ?? null}
              onSelect={setSelected}
              emptyDescription={
                graph.nodes.length
                  ? t("checkpoints.noMatches")
                  : t("checkpoints.empty")
              }
            />
          )}
        </div>
      </div>

      <Drawer
        open={!!selected}
        onClose={() => setSelected(null)}
        title={t("checkpoints.details")}
        width={440}
        extra={
          <Button
            type="primary"
            danger
            icon={<RotateCcw size={15} />}
            onClick={openRestore}
            disabled={!selected?.session_id}
          >
            {t("checkpoints.restore.action")}
          </Button>
        }
      >
        {selected && (
          <div className={styles.details}>
            <div className={styles.detailTitle}>
              {selected.query || selected.name || selected.subject}
            </div>
            <Descriptions column={1} size="small" colon={false}>
              <Descriptions.Item label={t("checkpoints.type")}>
                {t(
                  `checkpoints.kind.${
                    selected.kind === "snap"
                      ? "snapshot"
                      : selected.kind === "pre-restore"
                      ? "safety"
                      : selected.kind
                  }`,
                )}
              </Descriptions.Item>
              <Descriptions.Item label={t("checkpoints.commit")}>
                <span className={styles.commitValue}>
                  <code>{selected.commit}</code>
                  <Button
                    type="text"
                    size="small"
                    icon={<Copy size={14} />}
                    onClick={() =>
                      void navigator.clipboard.writeText(selected.commit)
                    }
                  />
                </span>
              </Descriptions.Item>
              <Descriptions.Item label={t("checkpoints.session")}>
                {selected.session_title ||
                  selected.session_id ||
                  selected.session_key}
              </Descriptions.Item>
              <Descriptions.Item label={t("checkpoints.channel")}>
                {selected.channel}
              </Descriptions.Item>
              <Descriptions.Item label={t("checkpoints.createdAt")}>
                {new Intl.DateTimeFormat(i18n.resolvedLanguage, {
                  dateStyle: "medium",
                  timeStyle: "medium",
                }).format(selected.timestamp_ms)}
              </Descriptions.Item>
              {selected.parent_commit && (
                <Descriptions.Item label={t("checkpoints.parent")}>
                  <code>{selected.parent_commit.slice(0, 12)}</code>
                </Descriptions.Item>
              )}
            </Descriptions>
          </div>
        )}
      </Drawer>

      <Modal
        open={snapshotOpen}
        title={t("checkpoints.snapshotDialog.title")}
        onCancel={() => setSnapshotOpen(false)}
        onOk={() => void createSnapshot()}
        confirmLoading={snapshotSaving}
        okText={t("checkpoints.snapshot")}
      >
        <div className={styles.snapshotForm}>
          <label>{t("checkpoints.snapshotDialog.session")}</label>
          <Select
            value={snapshotSession}
            onChange={setSnapshotSession}
            options={sessions
              .filter((item) => item.session_id)
              .map((item) => ({
                value: item.session_key,
                label: item.title || item.session_id,
              }))}
          />
          <label>{t("checkpoints.snapshotDialog.name")}</label>
          <Input
            value={snapshotName}
            maxLength={200}
            onChange={(event) => setSnapshotName(event.target.value)}
            placeholder={t("checkpoints.snapshotDialog.placeholder")}
          />
        </div>
      </Modal>

      <Modal
        open={gcSettingsOpen}
        title={t("checkpoints.gc.settingsTitle")}
        onCancel={() => setGcSettingsOpen(false)}
        onOk={() => void saveGcSettings()}
        confirmLoading={gcSettingsSaving}
        okButtonProps={{ disabled: gcSettingsLoading }}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        destroyOnHidden
      >
        <Spin spinning={gcSettingsLoading}>
          <Form form={gcSettingsForm} layout="vertical">
            <Form.Item
              name="gc_keep_count"
              label={t("checkpoints.gc.keepCount")}
              rules={[{ required: true }]}
            >
              <InputNumber
                min={0}
                max={1_000_000}
                precision={0}
                style={{ width: "100%" }}
              />
            </Form.Item>
            <Form.Item
              name="gc_keep_days"
              label={t("checkpoints.gc.keepDays")}
              rules={[{ required: true }]}
            >
              <InputNumber
                min={0}
                max={36_500}
                precision={0}
                style={{ width: "100%" }}
              />
            </Form.Item>
            <Form.Item
              name="pre_restore_retention_days"
              label={t("checkpoints.gc.preRestoreDays")}
              rules={[{ required: true }]}
            >
              <InputNumber
                min={0}
                max={36_500}
                precision={0}
                style={{ width: "100%" }}
              />
            </Form.Item>
          </Form>
        </Spin>
      </Modal>

      <RestoreModal
        open={restoreOpen}
        node={selected}
        onClose={() => setRestoreOpen(false)}
        onRestored={() => void load(true)}
      />
    </div>
  );
}
