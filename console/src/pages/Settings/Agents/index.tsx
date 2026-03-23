import { useState } from "react";
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
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import {
  AppstoreOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
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
import { PageHeader, AgentTable, AgentModal } from "./components";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t } = useTranslation();
  const { agents, loading, deleteAgent } = useAgents();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [squareVisible, setSquareVisible] = useState(false);
  const [squareLoading, setSquareLoading] = useState(false);
  const [squareSources, setSquareSources] =
    useState<AgentsSquareSourcesPayload | null>(null);
  const [squareItems, setSquareItems] =
    useState<AgentSquareItemsResponse | null>(null);
  const [sourceDrafts, setSourceDrafts] = useState<AgentsSquareSourceSpec[]>(
    [],
  );
  const [squareSearch, setSquareSearch] = useState("");
  const [squareSourceFilter, setSquareSourceFilter] =
    useState<string>("__all__");
  const [preferredImportName, setPreferredImportName] = useState("");
  const [importingKey, setImportingKey] = useState<string | null>(null);
  const [savingSources, setSavingSources] = useState(false);
  const [validatingSourceKey, setValidatingSourceKey] = useState<string | null>(
    null,
  );
  const [form] = Form.useForm();

  const handleCreate = () => {
    setEditingAgent(null);
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
    });
    setModalVisible(true);
  };

  const handleEdit = async (agent: AgentSummary) => {
    try {
      const config = await agentsApi.getAgent(agent.id);
      setEditingAgent(agent);
      form.setFieldsValue(config);
      setModalVisible(true);
    } catch (error) {
      console.error("Failed to load agent config:", error);
      message.error(t("agent.loadConfigFailed"));
    }
  };

  const handleDelete = async (agentId: string) => {
    try {
      await deleteAgent(agentId);
    } catch {
      // Error already handled in hook
      message.error(t("agent.deleteFailed"));
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
      isConflict: statusCode === 409 || msg.includes("AGENT_NAME_CONFLICT"),
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
    if (
      squareSourceFilter !== "__all__" &&
      item.source_id !== squareSourceFilter
    ) {
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
    setSourceDrafts((prev) => [
      ...prev,
      {
        id: "",
        name: "",
        type: "git",
        provider: "index_json_repo",
        url: "",
        branch: "",
        path: "index.json",
        enabled: true,
        order: prev.length + 1,
        trust: "community",
        license_hint: "",
        pinned: false,
      },
    ]);
  };

  const handleRemoveSourceDraft = (index: number) => {
    const source = sourceDrafts[index];
    if (!source || source.pinned) return;
    setSourceDrafts((prev) => prev.filter((_, i) => i !== index));
  };

  const handleValidateSourceDraft = async (index: number) => {
    const draft = sourceDrafts[index];
    if (!draft) return;
    const key = draft.id || `${index}`;
    setValidatingSourceKey(key);
    try {
      const result = await agentsApi.validateSquareSource(draft);
      updateSourceDraft(index, result.normalized);
      message.success(t("agent.squareValidateSuccess"));
    } catch (error) {
      console.error("Validate source failed:", error);
      message.error(t("agent.squareValidateFailed"));
    } finally {
      setValidatingSourceKey(null);
    }
  };

  const handleSaveSources = async () => {
    if (!squareSources) return;
    setSavingSources(true);
    try {
      const payload: AgentsSquareSourcesPayload = {
        version: squareSources.version,
        cache: squareSources.cache,
        install: squareSources.install,
        sources: sourceDrafts,
      };
      const saved = await agentsApi.updateSquareSources(payload);
      setSquareSources(saved);
      setSourceDrafts(saved.sources ?? []);
      message.success(t("agent.squareSaveSourcesSuccess"));
      await loadSquare(true);
    } catch (error) {
      console.error("Save sources failed:", error);
      message.error(t("agent.squareSaveSourcesFailed"));
    } finally {
      setSavingSources(false);
    }
  };

  return (
    <div className={styles.agentsPage}>
      <PageHeader
        title={t("agent.management")}
        description={t("agent.pageDescription")}
        action={
          <Space>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreate}
            >
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
            {t("agent.squareSourceCount")}:{" "}
            {squareItems?.meta?.source_count ?? 0} ·{" "}
            {t("agent.squareItemCount")}: {squareItems?.meta?.item_count ?? 0}
          </Typography.Paragraph>

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

          <Typography.Text type="secondary">
            {t("agent.squareSourcesLabel")}
          </Typography.Text>
          <List
            size="small"
            dataSource={squareSources?.sources ?? []}
            locale={{ emptyText: t("agent.squareNoSources") }}
            renderItem={(source) => (
              <List.Item>
                <List.Item.Meta
                  title={`${source.name} (${source.id})`}
                  description={`${source.provider} · ${source.url}`}
                />
              </List.Item>
            )}
          />

          <Divider style={{ margin: "8px 0" }} />
          <Space>
            <Typography.Text strong>
              {t("agent.squareSourcesEditTitle")}
            </Typography.Text>
            <Button size="small" onClick={handleAddSourceDraft}>
              {t("agent.squareAddSource")}
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

          <List
            size="small"
            dataSource={sourceDrafts}
            locale={{ emptyText: t("agent.squareNoSources") }}
            renderItem={(source, idx) => (
              <List.Item>
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
                        {
                          value: "agency_markdown_repo",
                          label: "agency_markdown_repo",
                        },
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
                        updateSourceDraft(idx, {
                          branch: e.target.value.trim(),
                        })
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
                    <Button
                      size="small"
                      danger
                      disabled={source.pinned}
                      onClick={() => handleRemoveSourceDraft(idx)}
                    >
                      {t("agent.squareRemoveSource")}
                    </Button>
                  </Space>

                  <Input
                    size="small"
                    name={`agents-square-source-url-${idx}`}
                    aria-label="source url"
                    placeholder="url"
                    value={source.url}
                    onChange={(e) =>
                      updateSourceDraft(idx, { url: e.target.value })
                    }
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
                </Space>
              </List.Item>
            )}
          />
        </Space>
      </Drawer>
    </div>
  );
}
