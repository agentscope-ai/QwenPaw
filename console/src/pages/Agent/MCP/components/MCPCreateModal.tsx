import { useState, useCallback } from "react";
import { Button, Modal, Input, Select } from "@agentscope-ai/design";
import { Tabs } from "antd";
import { useTranslation } from "react-i18next";
import {
  DEFAULT_MCP_JSON,
  defaultMcpForm,
  type MCPTransport,
} from "../utils/mcpClientUtils";
import parentStyles from "../index.module.less";

interface MCPCreateModalProps {
  open: boolean;
  onClose: () => void;
  onCreateFromJson: (json: string) => Promise<boolean>;
  onCreateFromForm: (form: typeof defaultMcpForm) => Promise<boolean>;
}

export function MCPCreateModal({
  open,
  onClose,
  onCreateFromJson,
  onCreateFromForm,
}: MCPCreateModalProps) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<"custom" | "json">("custom");
  const [newClientJson, setNewClientJson] = useState(DEFAULT_MCP_JSON);
  const [form, setForm] = useState({ ...defaultMcpForm });

  const setField = useCallback(
    <K extends keyof typeof defaultMcpForm>(
      k: K,
      v: (typeof defaultMcpForm)[K],
    ) => {
      setForm((prev) => ({ ...prev, [k]: v }));
    },
    [],
  );

  const resetModal = useCallback(() => {
    setNewClientJson(DEFAULT_MCP_JSON);
    setForm({ ...defaultMcpForm });
    setActiveTab("custom");
  }, []);

  const handleClose = () => {
    resetModal();
    onClose();
  };

  const handleCreate = async () => {
    if (activeTab === "json") {
      const ok = await onCreateFromJson(newClientJson);
      if (ok) {
        handleClose();
      }
    } else {
      const ok = await onCreateFromForm(form);
      if (ok) {
        handleClose();
      }
    }
  };

  const isHttpTransport =
    form.transport === "streamable_http" || form.transport === "sse";

  return (
    <Modal
      title={t("mcp.create")}
      open={open}
      onCancel={handleClose}
      footer={
        <div className={parentStyles.modalFooter}>
          <Button onClick={handleClose} style={{ marginRight: 8 }}>
            {t("common.cancel")}
          </Button>
          <Button type="primary" onClick={handleCreate}>
            {t("common.create")}
          </Button>
        </div>
      }
      width={800}
    >
      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as "custom" | "json")}
        items={[
          {
            key: "custom",
            label: t("mcp.tab.form"),
            children: (
              <div
                style={{ display: "flex", flexDirection: "column", gap: 10 }}
              >
                <div style={rowStyle}>
                  <div style={fieldStyle}>
                    <label style={labelStyle}>
                      {t("mcp.form.key")}
                      <span style={{ color: "#c0392b" }}> *</span>
                    </label>
                    <Input
                      placeholder={t("mcp.form.keyPlaceholder")}
                      value={form.key}
                      onChange={(e) => setField("key", e.target.value)}
                    />
                  </div>
                  <div style={fieldStyle}>
                    <label style={labelStyle}>
                      {t("mcp.form.name")}
                      <span style={{ color: "#c0392b" }}> *</span>
                    </label>
                    <Input
                      placeholder={t("mcp.form.namePlaceholder")}
                      value={form.name}
                      onChange={(e) => setField("name", e.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <label style={labelStyle}>{t("mcp.form.transport")}</label>
                  <Select
                    value={form.transport}
                    onChange={(v) => setField("transport", v as MCPTransport)}
                    style={{ width: "100%" }}
                    options={[
                      {
                        label: "Streamable HTTP",
                        value: "streamable_http",
                      },
                      { label: "SSE", value: "sse" },
                      { label: "Stdio", value: "stdio" },
                    ]}
                  />
                </div>

                {isHttpTransport ? (
                  <div>
                    <label style={labelStyle}>
                      {t("mcp.form.url")}
                      <span style={{ color: "#c0392b" }}> *</span>
                    </label>
                    <Input
                      placeholder="https://mcp.example.com/mcp"
                      value={form.url}
                      onChange={(e) => setField("url", e.target.value)}
                    />
                  </div>
                ) : (
                  <>
                    <div>
                      <label style={labelStyle}>
                        {t("mcp.form.command")}
                        <span style={{ color: "#c0392b" }}> *</span>
                      </label>
                      <Input
                        placeholder="npx"
                        value={form.command}
                        onChange={(e) => setField("command", e.target.value)}
                      />
                    </div>
                    <div>
                      <label style={labelStyle}>{t("mcp.form.args")}</label>
                      <Input
                        placeholder="-y @example/mcp-server"
                        value={form.args}
                        onChange={(e) => setField("args", e.target.value)}
                      />
                    </div>
                  </>
                )}

                <div>
                  <label style={labelStyle}>{t("mcp.form.description")}</label>
                  <Input
                    placeholder={t("mcp.form.descriptionPlaceholder")}
                    value={form.description}
                    onChange={(e) => setField("description", e.target.value)}
                  />
                </div>

                {form.transport === "stdio" && (
                  <div>
                    <label style={labelStyle}>{t("mcp.form.env")}</label>
                    <Input.TextArea
                      placeholder={t("mcp.form.envPlaceholder")}
                      value={form.env}
                      onChange={(e) => setField("env", e.target.value)}
                      autoSize={{ minRows: 2, maxRows: 5 }}
                    />
                  </div>
                )}
              </div>
            ),
          },
          {
            key: "json",
            label: t("mcp.advanced.jsonImport"),
            children: (
              <div>
                <p className={parentStyles.importHintTitle}>
                  {t("mcp.advanced.hint")}
                </p>
                <div className={parentStyles.importHint}>
                  <p className={parentStyles.importHintTitle}>
                    {t("mcp.formatSupport")}:
                  </p>
                  <ul className={parentStyles.importHintList}>
                    <li>
                      {t("mcp.standardFormat")}:{" "}
                      <code>{`{ "mcpServers": { "key": {...} } }`}</code>
                    </li>
                    <li>
                      {t("mcp.directFormat")}: <code>{`{ "key": {...} }`}</code>
                    </li>
                    <li>
                      {t("mcp.singleFormat")}:{" "}
                      <code>{`{ "key": "...", "name": "...", "command": "..." }`}</code>
                    </li>
                  </ul>
                </div>
                <Input.TextArea
                  value={newClientJson}
                  onChange={(e) => setNewClientJson(e.target.value)}
                  autoSize={{ minRows: 15, maxRows: 25 }}
                  className={parentStyles.jsonTextArea}
                />
              </div>
            ),
          },
        ]}
      />
    </Modal>
  );
}

const rowStyle: React.CSSProperties = {
  display: "flex",
  gap: 12,
};

const fieldStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  color: "#555",
  fontWeight: 500,
};
