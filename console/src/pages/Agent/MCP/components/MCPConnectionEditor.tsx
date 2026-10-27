import { useId, useState } from "react";
import { Alert, Button, Input, Segmented } from "antd";
import { Code2, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./MCPConnectionEditor.module.less";

import { readConnection, connectionError } from "./connectionValue";

/** Edit connection essentials directly, retaining arbitrary advanced properties. */
export function MCPConnectionEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [advanced, setAdvanced] = useState(false);
  const config = readConnection(value);
  const error = connectionError(config);
  const set = (key: string, next: unknown) =>
    onChange(JSON.stringify({ ...config, [key]: next }, null, 2));
  const field = (key: string, label: string, multiline = false) => (
    <div className={styles.field} key={key}>
      <label htmlFor={`${id}-${key}`}>{label}</label>
      {multiline ? (
        <Input.TextArea
          id={`${id}-${key}`}
          defaultValue={
            Array.isArray(config?.[key])
              ? (config[key] as string[]).join("\n")
              : ""
          }
          onChange={(event) =>
            set(
              key,
              event.target.value.split("\n").filter((line) => line.length > 0),
            )
          }
          autoSize={{ minRows: 2, maxRows: 5 }}
        />
      ) : (
        <Input
          id={`${id}-${key}`}
          value={String(config?.[key] ?? "")}
          onChange={(event) => set(key, event.target.value)}
        />
      )}
    </div>
  );
  return (
    <div className={styles.editor}>
      <div className={styles.toolbar}>
        <span>{String(config?.key ?? "")}</span>
        <Button
          type="text"
          icon={
            advanced ? <SlidersHorizontal size={16} /> : <Code2 size={16} />
          }
          onClick={() => setAdvanced(!advanced)}
          disabled={advanced && !config}
        >
          {t(advanced ? "common.configure" : "common.advancedSettings")}
        </Button>
      </div>
      {(advanced || !config) && (
        <p className={styles.hint}>{t("mcp.maskedFieldHint")}</p>
      )}
      {advanced || !config ? (
        <Input.TextArea
          aria-label="JSON"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoSize={{ minRows: 10, maxRows: 20 }}
          className={styles.json}
        />
      ) : (
        <>
          {field("name", t("mcp.form.name"))}
          <div className={styles.field}>
            <label>{t("mcp.form.transport")}</label>
            <Segmented
              block
              aria-label={t("mcp.form.transport")}
              value={String(config.transport)}
              options={[
                { value: "stdio", label: "Stdio" },
                {
                  value: "streamable_http",
                  label: <span title="Streamable HTTP">HTTP</span>,
                },
                { value: "sse", label: "SSE" },
              ]}
              onChange={(next) => set("transport", next)}
            />
          </div>
          {config.transport === "stdio" ? (
            <>
              {field("command", t("mcp.form.command"))}
              {field("args", `${t("acp.args")} · ${t("acp.argsHelp")}`, true)}
            </>
          ) : (
            field("url", t("mcp.form.url"))
          )}
          {field("description", t("mcp.form.description"))}
        </>
      )}
      {error && <Alert type="error" message={t(error)} />}
    </div>
  );
}
