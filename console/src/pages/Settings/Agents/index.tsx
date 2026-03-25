import { useEffect, useState } from "react";
import {
  Card,
  Button,
  Checkbox,
  Drawer,
  Divider,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Select,
  Switch,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { AppstoreOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import type {
  AgentSquareItem,
  AgentSummary,
  AgentSquareItemsResponse,
  AgentsSquareSourceSpec,
  AgentsSquareSourcesPayload,
} from "../../../api/types/agents";
import { useAgents } from "./useAgents";
import { useAgentStore } from "../../../stores/agentStore";
import { PageHeader, AgentTable, AgentModal } from "./components";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t } = useTranslation();
  const { agents, loading, deleteAgent, toggleAgent, loadAgents } = useAgents();
  const { selectedAgent, setSelectedAgent } = useAgentStore();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [squareVisible, setSquareVisible] = useState(false);
  const [squareLoading, setSquareLoading] = useState(false);
  const [squareSources, setSquareSources] =
    useState<AgentsSquareSourcesPayload | null>(null);
  const [squareItems, setSquareItems] = useState<AgentSquareItemsResponse | null>(
    null,
  );
  const [sourceDrafts, setSourceDrafts] = useState<AgentsSquareSourceSpec[]>([]);
  const [editingSourceIdx, setEditingSourceIdx] = useState<number | null>(null);
  const [sourceEditBackup, setSourceEditBackup] =
    useState<AgentsSquareSourceSpec | null>(null);
  const [squareSearch, setSquareSearch] = useState("");
  const [squareSourceFilter, setSquareSourceFilter] = useState<string>("__all__");
  const [preferredImportName, setPreferredImportName] = useState("");
  const [importingKey, setImportingKey] = useState<string | null>(null);
  const [savingSources, setSavingSources] = useState(false);
  const [togglingSourceKey, setTogglingSourceKey] = useState<string | null>(null);
  const [validatingSourceKey, setValidatingSourceKey] = useState<string | null>(null);
  const [pendingFormValues, setPendingFormValues] =
    useState<Record<string, unknown> | null>(null);
  const [form] = Form.useForm();

  const handleCreate = () => {
    setEditingAgent(null);
    setPendingFormValues({
      workspace_dir: "",
    });
    setModalVisible(true);
  };

  const handleEdit = async (agent: AgentSummary) => {
    try {
      const config = await agentsApi.getAgent(agent.id);
      setEditingAgent(agent);
      setPendingFormValues(config as unknown as Record<string, unknown>);
      setModalVisible(true);
    } catch (error) {
      console.error("Failed to load agent config:", error);
      message.error(t("agent.loadConfigFailed"));
    }
  };

  useEffect(() => {
    if (!modalVisible) {
      return;
    }

    if (pendingFormValues) {
      form.setFieldsValue(pendingFormValues);
      return;
    }

    form.resetFields();
  }, [form, modalVisible, pendingFormValues]);

  const handleDelete = async (agentId: string) => {
    try {
      await deleteAgent(agentId);
    } catch {
      // Error already handled in hook
      message.error(t("agent.deleteFailed"));
    }
  };

  const handleToggle = async (agentId: string, currentEnabled: boolean) => {
    const newEnabled = !currentEnabled;
    try {
      await toggleAgent(agentId, newEnabled);

      // If disabling the current agent, switch to default
      if (!newEnabled && selectedAgent === agentId) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
    } catch {
      // Error already handled in hook
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (editingAgent) {
        await agentsApi.updateAgent(editingAgent.id, values);
        message.success(t("agent.updateSuccess"));
      } else {
        const result = await agentsApi.createAgent(values);
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
      }

      setModalVisible(false);
    } catch (error: unknown) {
      console.error("Failed to save agent:", error);
      const errorMessage = error instanceof Error ? error.message : undefined;
      message.error(errorMessage || t("agent.saveFailed"));
    }
  };

  const loadSquare = async (refresh = false) => {
    setSquareLoading(true);
    try {
      const [sources, items] = await Promise.all([
        agentsApi.getSquareSources(),
        agentsApi.getSquareItems(refresh),
      ]);
      setSquareSources(sources);
      setSourceDrafts(sources.sources ?? []);
      setSquareItems(items);
    } catch (error) {
      console.error("Failed to load Agents Square:", error);
      message.error(t("agent.squareLoadFailed"));
    } finally {
      setSquareLoading(false);
    }
  };

  const handleOpenSquare = async () => {
    setSquareVisible(true);
    await loadSquare(false);
  };

  const parseSquareError = (error: unknown) => {
    const msg = error instanceof Error ? error.message : String(error);
    const statusMatch = msg.match(/Request failed:\s*(\d+)/i);
    const statusCode = statusMatch ? Number(statusMatch[1]) : 0;
    return {
      statusCode,
      isConflict:
        statusCode === 409 || msg.includes("AGENT_NAME_CONFLICT"),
      message: msg,
    };
  };

  const handleImportSquareItem = async (
    item: AgentSquareItem,
    overwrite = false,
  ) => {
    const key = `${item.source_id}/${item.agent_id}`;
    setImportingKey(key);
    try {
      const result = await agentsApi.importSquareAgent({
        source_id: item.source_id,
        agent_id: item.agent_id,
        overwrite,
        enable: true,
        preferred_name: preferredImportName.trim() || undefined,
      });
      message.success(
        `${t("agent.createSuccess")} (${result.name}, ID: ${result.id})`,
      );
      await loadSquare(true);
      return true;
    } catch (error) {
      const parsed = parseSquareError(error);
      if (parsed.isConflict && !overwrite) {
        const confirmed = await new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: t("agent.squareConflictTitle"),
            content: t("agent.squareConflictDesc", {
              name: item.name,
            }),
            okText: t("agent.squareOverwrite"),
            cancelText: t("agent.squareClose"),
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        });
        if (confirmed) {
          return await handleImportSquareItem(item, true);
        }
        return false;
      }
      console.error("Failed to import square agent:", error);
      message.error(parsed.message || t("agent.squareImportFailed"));
      return false;
    } finally {
      setImportingKey(null);
    }
  };

  const sourceOptions = (squareSources?.sources ?? []).map((source) => ({
    label: `${source.name} (${source.id})`,
    value: source.id,
  }));

  const allSquareItems = squareItems?.items ?? [];
  const normalizedSearch = squareSearch.trim().toLowerCase();
  const filteredSquareItems = allSquareItems.filter((item) => {
    if (squareSourceFilter !== "__all__" && item.source_id !== squareSourceFilter) {
      return false;
    }
    if (!normalizedSearch) return true;
    const haystack = [
      item.name,
      item.agent_id,
      item.description,
      item.source_id,
      ...(item.tags ?? []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalizedSearch);
  });

  const updateSourceDraft = (
    index: number,
    patch: Partial<AgentsSquareSourceSpec>,
  ) => {
    setSourceDrafts((prev) =>
      prev.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    );
  };

  const handleAddSourceDraft = () => {
    const nextDraft: AgentsSquareSourceSpec = {
      id: "",
      name: "",
      type: "git",
      provider: "index_json_repo",
      url: "",
      branch: "",
      path: "index.json",
      enabled: true,
      order: sourceDrafts.length + 1,
      trust: "community",
      license_hint: "",
      pinned: false,
    };
    setEditingSourceIdx(sourceDrafts.length);
    setSourceEditBackup({ ...nextDraft });
    setSourceDrafts((prev) => [...prev, nextDraft]);
  };

  const handleEditSourceDraft = (index: number) => {
    const source = sourceDrafts[index];
    if (!source) return;
    setEditingSourceIdx(index);
    setSourceEditBackup({ ...source });
  };

  const handleCancelEditSourceDraft = () => {
    if (editingSourceIdx === null) return;
    if (sourceEditBackup) {
      const idx = editingSourceIdx;
      setSourceDrafts((prev) =>
        prev.map((item, i) => (i === idx ? sourceEditBackup : item)),
      );
    }
    setEditingSourceIdx(null);
    setSourceEditBackup(null);
  };

  const handleSaveEditSourceDraft = () => {
    setEditingSourceIdx(null);
    setSourceEditBackup(null);
  };

  const handleRemoveSourceDraft = (index: number) => {
    const source = sourceDrafts[index];
    if (!source || source.pinned) return;
    setSourceDrafts((prev) => prev.filter((_, i) => i !== index));
    setEditingSourceIdx((current) => {
      if (current === null) return current;
      if (current === index) return null;
      if (current > index) return current - 1;
      return current;
    });
  };

  const inferSourceNameFromUrl = (raw: string) => {
    const text = (raw || "").trim();
    if (!text) return "";

    const parseOwnerRepo = (candidate: string) => {
      const cleaned = candidate.replace(/^\/+|\/+$/g, "");
      const parts = cleaned.split("/").filter(Boolean);
      if (parts.length >= 2) {
        return parts[1].replace(/\.git$/i, "");
      }
      return "";
    };

    try {
      const u = new URL(text);
      if (u.hostname.includes("github.com")) {
        const repo = parseOwnerRepo(u.pathname);
        if (repo) return repo;
      }
      const hostFirst = u.hostname.split(".").filter(Boolean)[0];
      return hostFirst || "";
    } catch {
      const noProto = text.replace(/^https?:\/\//, "");
      if (noProto.includes("/")) {
        return parseOwnerRepo(noProto);
      }
      return "";
    }
  };

  const parseGithubSpec = (raw: string) => {
    const text = (raw || "").trim();
    if (!text) return null;
    try {
      const u = new URL(text);
      if (!u.hostname.includes("github.com")) return null;
      const parts = u.pathname.split("/").filter(Boolean);
      if (parts.length < 2) return null;
      const owner = parts[0];
      const repo = parts[1].replace(/\.git$/i, "");
      let branch = "";
      let path = "";
      if (parts.length >= 4 && (parts[2] === "tree" || parts[2] === "blob")) {
        branch = parts[3];
        if (parts.length > 4) {
          path = parts.slice(4).join("/");
        }
      }
      return { owner, repo, branch, path };
    } catch {
      return null;
    }
  };

  const inferSourceIdFromUrl = (raw: string) => {
    const spec = parseGithubSpec(raw);
    if (spec) {
      return `${spec.owner}-${spec.repo}`.toLowerCase();
    }
    const text = (raw || "").trim().replace(/^https?:\/\//, "");
    const parts = text.split("/").filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0]}-${parts[1].replace(/\.git$/i, "")}`.toLowerCase();
    }
    return "";
  };

  const maybeAutofillSourceDraft = (
    idx: number,
    source: AgentsSquareSourceSpec,
  ) => {
    const patch: Partial<AgentsSquareSourceSpec> = {};
    const githubSpec = parseGithubSpec(source.url);

    if (!source.id?.trim()) {
      const inferredId = inferSourceIdFromUrl(source.url);
      if (inferredId) {
        patch.id = inferredId;
      }
    }

    if (!source.name?.trim()) {
      const inferredName = inferSourceNameFromUrl(source.url);
      if (inferredName) {
        patch.name = inferredName;
      }
    }

    const isDefaultIndexContract =
      source.provider === "index_json_repo" && (!source.path || source.path === "index.json");

    if (githubSpec) {
      if (githubSpec.branch && !source.branch?.trim()) {
        patch.branch = githubSpec.branch;
      }
      if (githubSpec.path) {
        if (!source.path || source.path === "index.json" || source.path === ".") {
          patch.path = githubSpec.path;
        }
        if (isDefaultIndexContract) {
          patch.provider = githubSpec.path.endsWith(".json")
            ? "index_json_repo"
            : "agency_markdown_repo";
        }
      } else if (isDefaultIndexContract) {
        patch.provider = "agency_markdown_repo";
        patch.path = ".";
      }
    }

    if (Object.keys(patch).length === 0) {
      return source;
    }

    updateSourceDraft(idx, patch);
    return { ...source, ...patch };
  };

  const handleValidateSourceDraft = async (index: number) => {
    const current = sourceDrafts[index];
    if (!current) return;
    const draft = maybeAutofillSourceDraft(index, current);
    if (!draft) return;
    const key = draft.id || `${index}`;
    setValidatingSourceKey(key);
    try {
      const result = await agentsApi.validateSquareSource(draft);
      updateSourceDraft(index, result.normalized);
      if (editingSourceIdx === index) {
        setSourceEditBackup(result.normalized);
      }
      message.success(t("agent.squareValidateSuccess"));
    } catch (error) {
      console.error("Validate source failed:", error);
      message.error(t("agent.squareValidateFailed"));
    } finally {
      setValidatingSourceKey(null);
    }
  };

  const persistSquareSources = async (
    nextSources: AgentsSquareSourceSpec[],
    options?: {
      notifySuccess?: boolean;
      notifyError?: boolean;
      refreshItems?: boolean;
    },
  ) => {
    if (!squareSources) return;
    const {
      notifySuccess = true,
      notifyError = true,
      refreshItems = true,
    } = options ?? {};

    setSavingSources(true);
    try {
      const payload: AgentsSquareSourcesPayload = {
        version: squareSources.version,
        cache: squareSources.cache,
        install: squareSources.install,
        sources: nextSources,
      };
      const saved = await agentsApi.updateSquareSources(payload);
      setSquareSources(saved);
      setSourceDrafts(saved.sources ?? []);
      setEditingSourceIdx(null);
      setSourceEditBackup(null);
      if (notifySuccess) {
        message.success(t("agent.squareSaveSourcesSuccess"));
      }
      if (refreshItems) {
        await loadSquare(true);
      }
      return true;
    } catch (error) {
      console.error("Save sources failed:", error);
      if (notifyError) {
        message.error(t("agent.squareSaveSourcesFailed"));
      }
      return false;
    } finally {
      setSavingSources(false);
    }
  };

  const handleSaveSources = async () => {
    await persistSquareSources(sourceDrafts);
  };

  const handleResetSquareSources = async () => {
    Modal.confirm({
      title: t("agent.squareResetTemplate"),
      content: t("agent.squareResetTemplateConfirm"),
      okType: "danger",
      onOk: async () => {
        const resetPayload = await agentsApi.resetSquareSources();
        setSquareSources(resetPayload);
        setSourceDrafts(resetPayload.sources ?? []);
        setEditingSourceIdx(null);
        setSourceEditBackup(null);
        await loadSquare(true);
        message.success(t("agent.squareSaveSourcesSuccess"));
      },
    });
  };

  const handleToggleSourceEnabled = async (index: number, enabled: boolean) => {
    const current = sourceDrafts[index];
    if (!current || !squareSources) return;

    const key = current.id || `${index}`;
    const prevSources = sourceDrafts;
    const nextSources = sourceDrafts.map((item, i) =>
      i === index ? { ...item, enabled } : item,
    );
    setSourceDrafts(nextSources);
    setTogglingSourceKey(key);

    const ok = await persistSquareSources(nextSources, {
      notifySuccess: false,
      notifyError: true,
      refreshItems: true,
    });
    if (!ok) {
      setSourceDrafts(prevSources);
    }
    setTogglingSourceKey(null);
  };

  return (
    <div className={styles.agentsPage}>
      <PageHeader
        title={t("agent.management")}
        description={t("agent.pageDescription")}
        action={
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
              {t("agent.create")}
            </Button>
            <Button icon={<AppstoreOutlined />} onClick={handleOpenSquare}>
              {t("agent.square")}
            </Button>
          </Space>
        }
      />

      <Card className={styles.tableCard}>
        <AgentTable
          agents={agents}
          loading={loading}
          onEdit={handleEdit}
          onDelete={handleDelete}
          onToggle={handleToggle}
        />
      </Card>

      <AgentModal
        open={modalVisible}
        editingAgent={editingAgent}
        form={form}
        onSave={handleSubmit}
        onCancel={() => setModalVisible(false)}
      />

      <Drawer
        open={squareVisible}
        title={t("agent.square")}
        onClose={() => setSquareVisible(false)}
        placement="right"
        width="80vw"
        footer={[
          <Button
            key="refresh"
            icon={<ReloadOutlined />}
            loading={squareLoading}
            onClick={() => loadSquare(true)}
          >
            {t("agent.squareRefresh")}
          </Button>,
          <Button key="close" onClick={() => setSquareVisible(false)}>
            {t("agent.squareClose")}
          </Button>,
        ]}
      >
        <Typography.Paragraph type="secondary">
          {t("agent.squareDescription")}
        </Typography.Paragraph>
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Paragraph>
            {t("agent.squareSourceCount")}: {squareItems?.meta?.source_count ?? 0} ·{" "}
            {t("agent.squareItemCount")}: {squareItems?.meta?.item_count ?? 0}
          </Typography.Paragraph>

          <Typography.Text type="secondary">
            {t("agent.squareSourcesLabel")}
          </Typography.Text>
          <Space>
            <Typography.Text strong>{t("agent.squareSourcesEditTitle")}</Typography.Text>
            <Button size="small" onClick={handleAddSourceDraft}>
              {t("agent.squareAddSource")}
            </Button>
            <Button size="small" onClick={handleResetSquareSources}>
              {t("agent.squareResetTemplate")}
            </Button>
            <Button
              size="small"
              type="primary"
              loading={savingSources}
              onClick={handleSaveSources}
            >
              {t("agent.squareSaveSources")}
            </Button>
          </Space>
          <Typography.Text type="secondary">
            {t("agent.squareSourceUrlExample")}
          </Typography.Text>

          <List
            size="small"
            dataSource={sourceDrafts}
            locale={{ emptyText: t("agent.squareNoSources") }}
            renderItem={(source, idx) => (
              <List.Item>
                {editingSourceIdx === idx ? (
                  <Space direction="vertical" size={6} style={{ width: "100%" }}>
                    <Space wrap>
                      <Input
                        size="small"
                        name={`agents-square-source-id-${idx}`}
                        aria-label="source id"
                        style={{ width: 160 }}
                        placeholder="id"
                        value={source.id}
                        disabled={source.pinned}
                        onChange={(e) =>
                          updateSourceDraft(idx, { id: e.target.value.trim() })
                        }
                      />
                      <Input
                        size="small"
                        name={`agents-square-source-name-${idx}`}
                        aria-label="source name"
                        style={{ width: 180 }}
                        placeholder="name"
                        value={source.name}
                        onChange={(e) =>
                          updateSourceDraft(idx, { name: e.target.value })
                        }
                      />
                      <Select
                        size="small"
                        style={{ width: 170 }}
                        value={source.provider}
                        options={[
                          { value: "agency_markdown_repo", label: "agency_markdown_repo" },
                          { value: "index_json_repo", label: "index_json_repo" },
                        ]}
                        onChange={(value) =>
                          updateSourceDraft(idx, {
                            provider: value,
                            path:
                              value === "agency_markdown_repo"
                                ? source.path || "."
                                : source.path || "index.json",
                          })
                        }
                      />
                      <Select
                        size="small"
                        style={{ width: 140 }}
                        value={source.trust || "community"}
                        options={[
                          { value: "official", label: "official" },
                          { value: "community", label: "community" },
                          { value: "custom", label: "custom" },
                        ]}
                        onChange={(value) =>
                          updateSourceDraft(idx, {
                            trust: value as "official" | "community" | "custom",
                          })
                        }
                      />
                      <InputNumber
                        size="small"
                        name={`agents-square-source-order-${idx}`}
                        aria-label="source order"
                        style={{ width: 90 }}
                        min={0}
                        value={source.order}
                        onChange={(value) =>
                          updateSourceDraft(idx, { order: Number(value ?? 999) })
                        }
                      />
                      <Input
                        size="small"
                        name={`agents-square-source-branch-${idx}`}
                        aria-label="source branch"
                        style={{ width: 120 }}
                        placeholder="branch"
                        value={source.branch || ""}
                        onChange={(e) =>
                          updateSourceDraft(idx, { branch: e.target.value.trim() })
                        }
                      />
                      <Input
                        size="small"
                        name={`agents-square-source-path-${idx}`}
                        aria-label="source path"
                        style={{ width: 160 }}
                        placeholder="path"
                        value={source.path || ""}
                        onChange={(e) =>
                          updateSourceDraft(idx, { path: e.target.value.trim() })
                        }
                      />
                      <Checkbox
                        name={`agents-square-source-enabled-${idx}`}
                        aria-label={t("agent.squareSourceEnabled")}
                        checked={source.enabled}
                        onChange={(e) =>
                          updateSourceDraft(idx, { enabled: e.target.checked })
                        }
                      >
                        {t("agent.squareSourceEnabled")}
                      </Checkbox>
                      <Button
                        size="small"
                        loading={validatingSourceKey === (source.id || `${idx}`)}
                        onClick={() => handleValidateSourceDraft(idx)}
                      >
                        {t("agent.squareValidate")}
                      </Button>
                    </Space>

                    <Input
                      size="small"
                      name={`agents-square-source-url-${idx}`}
                      aria-label="source url"
                      placeholder="url"
                      value={source.url}
                      autoFocus
                      onChange={(e) => updateSourceDraft(idx, { url: e.target.value })}
                      onBlur={() => {
                        maybeAutofillSourceDraft(idx, source);
                      }}
                    />
                    <Input
                      size="small"
                      name={`agents-square-source-license-${idx}`}
                      aria-label="source license hint"
                      placeholder="license_hint"
                      value={source.license_hint || ""}
                      onChange={(e) =>
                        updateSourceDraft(idx, { license_hint: e.target.value })
                      }
                    />

                    <Space>
                      <Button size="small" type="primary" onClick={handleSaveEditSourceDraft}>
                        {t("common.save")}
                      </Button>
                      <Button size="small" onClick={handleCancelEditSourceDraft}>
                        {t("common.cancel")}
                      </Button>
                      <Button
                        size="small"
                        danger
                        disabled={source.pinned}
                        onClick={() => handleRemoveSourceDraft(idx)}
                      >
                        {t("agent.squareRemoveSource")}
                      </Button>
                    </Space>
                  </Space>
                ) : (
                  <div className={styles.squareSourceReadonlyRow}>
                    <div className={styles.squareSourceReadonlyInfo}>
                      <Typography.Text strong>
                        {source.name || "—"}
                      </Typography.Text>
                      <Typography.Text type="secondary">
                        {source.id || "—"}
                      </Typography.Text>
                      <Typography.Text type="secondary" ellipsis={{ tooltip: source.url }}>
                        {source.url || "—"}
                      </Typography.Text>
                      <Space wrap size={6}>
                        <Tag>{source.provider}</Tag>
                        <Tag>{source.path || "."}</Tag>
                        <Tag>{source.branch || "main"}</Tag>
                        <Tag color={source.enabled ? "green" : "default"}>
                          {source.enabled ? t("common.enabled") : t("common.disabled")}
                        </Tag>
                      </Space>
                    </div>
                    <Space>
                      <Switch
                        size="small"
                        checked={source.enabled}
                        loading={togglingSourceKey === (source.id || `${idx}`)}
                        onChange={(checked) => {
                          void handleToggleSourceEnabled(idx, checked);
                        }}
                      />
                      <Button size="small" onClick={() => handleEditSourceDraft(idx)}>
                        {t("common.edit")}
                      </Button>
                      <Button
                        size="small"
                        loading={validatingSourceKey === (source.id || `${idx}`)}
                        onClick={() => handleValidateSourceDraft(idx)}
                      >
                        {t("agent.squareValidate")}
                      </Button>
                      <Button
                        size="small"
                        danger
                        disabled={source.pinned}
                        onClick={() => handleRemoveSourceDraft(idx)}
                      >
                        {t("agent.squareRemoveSource")}
                      </Button>
                    </Space>
                  </div>
                )}
              </List.Item>
            )}
          />

          <Divider style={{ margin: "8px 0" }} />

          <Space wrap>
            <Select
              aria-label={t("agent.squareAllSources")}
              value={squareSourceFilter}
              style={{ minWidth: 240 }}
              onChange={setSquareSourceFilter}
              options={[
                { value: "__all__", label: t("agent.squareAllSources") },
                ...sourceOptions,
              ]}
            />
            <Input
              allowClear
              name="agents-square-search"
              aria-label={t("agent.squareSearchPlaceholder")}
              style={{ minWidth: 280 }}
              value={squareSearch}
              onChange={(e) => setSquareSearch(e.target.value)}
              placeholder={t("agent.squareSearchPlaceholder")}
            />
            <Input
              allowClear
              name="agents-square-preferred-name"
              aria-label={t("agent.squarePreferredNamePlaceholder")}
              style={{ minWidth: 280 }}
              value={preferredImportName}
              onChange={(e) => setPreferredImportName(e.target.value)}
              placeholder={t("agent.squarePreferredNamePlaceholder")}
            />
          </Space>

          <List
            loading={squareLoading}
            size="small"
            dataSource={filteredSquareItems}
            className={styles.squareList}
            locale={{ emptyText: t("agent.squareNoItems") }}
            renderItem={(item) => {
              const key = `${item.source_id}/${item.agent_id}`;
              return (
                <List.Item
                  className={styles.squareListItem}
                  actions={[
                    <Button
                      key="import"
                      type="primary"
                      size="small"
                      loading={importingKey === key}
                      onClick={() => handleImportSquareItem(item)}
                    >
                      {t("agent.squareImport")}
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space wrap>
                        <span>{item.name}</span>
                        <Tag>{item.source_id}</Tag>
                        <Tag>{item.agent_id}</Tag>
                      </Space>
                    }
                    description={
                      <Space direction="vertical" size={2}>
                        <Typography.Text type="secondary">
                          {item.description || t("agent.description")}
                        </Typography.Text>
                        {(item.tags || []).length > 0 && (
                          <Space wrap>
                            {(item.tags || []).slice(0, 6).map((tag) => (
                              <Tag key={tag}>{tag}</Tag>
                            ))}
                          </Space>
                        )}
                      </Space>
                    }
                  />
                </List.Item>
              );
            }}
          />
        </Space>
      </Drawer>
    </div>
  );
}
