import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createQwenPawDataApi,
  type ConnectionTestResult,
  type DataAppConfig,
  type QwenPawDataApi,
} from "./api";
import type { PawAppSdk } from "./sdk";
import { useT } from "./language";

/**
 * Quick-fill presets for OpenAI-compatible endpoints. The context service
 * only speaks the OpenAI protocol, so this catalog mirrors the host's
 * OpenAI-compatible providers rather than its full provider list.
 */
const PROVIDER_PRESETS = [
  {
    id: "openai",
    name: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
  },
  {
    id: "dashscope",
    name: "DashScope (Aliyun)",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
  },
  {
    id: "kimi",
    name: "Kimi (Moonshot)",
    baseUrl: "https://api.moonshot.cn/v1",
  },
  {
    id: "zhipu",
    name: "Zhipu (BigModel)",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
  },
  {
    id: "siliconflow",
    name: "SiliconFlow",
    baseUrl: "https://api.siliconflow.cn/v1",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
  },
  {
    id: "modelscope",
    name: "ModelScope",
    baseUrl: "https://api-inference.modelscope.cn/v1",
  },
  {
    id: "ollama",
    name: "Ollama (local)",
    baseUrl: "http://localhost:11434/v1",
  },
  {
    id: "lmstudio",
    name: "LM Studio (local)",
    baseUrl: "http://localhost:1234/v1",
  },
  {
    id: "custom",
    name: "Custom",
    baseUrl: "",
  },
] as const;

function emptyConfig(): DataAppConfig {
  return {
    version: 1,
    llm: {
      provider: "openai",
      base_url: "",
      model: "",
      api_key: "",
      reuse_host: false,
      host_provider_name: "",
    },
    embedding: {
      base_url: "",
      model: "",
      dim: 1024,
      api_key: "",
      reuse_host: false,
      host_provider_name: "",
    },
    neo4j: { uri: "", user: "neo4j", password: "", database: "" },
    // Not user-editable here: the embedded management console owns the
    // active selection, and the proxy backend mirrors it into this field.
    datasources: { active_id: "" },
  };
}

function mergeSaved(saved: Partial<DataAppConfig> | null): DataAppConfig {
  const base = emptyConfig();
  if (!saved) return base;
  return {
    version: saved.version ?? base.version,
    llm: { ...base.llm, ...saved.llm },
    embedding: { ...base.embedding, ...saved.embedding },
    neo4j: { ...base.neo4j, ...saved.neo4j },
    datasources: { ...base.datasources, ...saved.datasources },
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function updateField<T extends Record<string, unknown>>(
  section: T,
  key: keyof T,
  value: unknown,
): T {
  return { ...section, [key]: value };
}

/** Select that maps a preset onto base_url (and provider for LLM). */
function ProviderPresetSelect({
  id,
  baseUrl,
  onSelect,
}: {
  id: string;
  baseUrl: string;
  onSelect(preset: (typeof PROVIDER_PRESETS)[number]): void;
}) {
  const t = useT();
  const matched =
    PROVIDER_PRESETS.find(
      (preset) => preset.baseUrl && preset.baseUrl === baseUrl,
    ) ?? PROVIDER_PRESETS.find((preset) => preset.id === "custom");
  return (
    <div className="qwenpaw-data-configure__field">
      <label htmlFor={`provider-preset-${id}`}>
        {t("configure.providerPreset")}
      </label>
      <select
        id={`provider-preset-${id}`}
        value={matched?.id ?? ""}
        onChange={(event) => {
          const preset = PROVIDER_PRESETS.find(
            (candidate) => candidate.id === event.target.value,
          );
          if (preset) onSelect(preset);
        }}
      >
        {PROVIDER_PRESETS.map((preset) => (
          <option key={preset.id} value={preset.id}>
            {preset.id === "custom"
              ? t("configure.providerCustom")
              : preset.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Creator-style reuse toggle: checking it collapses the manual fields. */
function ReuseHostToggle({
  api,
  target,
  checked,
  onApplied,
}: {
  api: QwenPawDataApi;
  target: "llm" | "embedding";
  checked: boolean;
  onApplied(config: DataAppConfig): void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function toggle(next: boolean) {
    setBusy(true);
    setError("");
    try {
      onApplied(mergeSaved(await api.setReuseHost({ target, reuse: next })));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qwenpaw-data-configure__reuse">
      <label className="qwenpaw-data-configure__reuse-label">
        <input
          type="checkbox"
          checked={checked}
          disabled={busy}
          onChange={(event) => void toggle(event.target.checked)}
        />
        <span>
          {target === "llm"
            ? t("configure.reuseHost.llm")
            : t("configure.reuseHost.embedding")}
        </span>
      </label>
      {busy ? (
        <span className="qwenpaw-data-configure__reuse-status">
          {t("configure.reuseHost.applying")}
        </span>
      ) : null}
      {error ? (
        <p className="qwenpaw-data-configure__ds-hint is-error">{error}</p>
      ) : null}
    </div>
  );
}

export function Configure({
  paw,
  onRestart,
}: {
  paw: PawAppSdk;
  onRestart(): void;
}) {
  const api = useMemo(() => createQwenPawDataApi(paw), [paw]);
  const t = useT();
  const [config, setConfig] = useState<DataAppConfig>(emptyConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<
    Record<string, ConnectionTestResult>
  >({});

  useEffect(() => {
    let cancelled = false;
    api
      .getConfig()
      .then((saved) => {
        if (!cancelled) setConfig(mergeSaved(saved));
      })
      .catch((error) => {
        if (!cancelled) {
          setSaveResult({
            type: "error",
            message: errorMessage(error),
          });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  const setSection = useCallback(
    <K extends keyof DataAppConfig>(section: K, value: DataAppConfig[K]) => {
      setConfig((prev) => ({ ...prev, [section]: value }));
      setSaveResult(null);
    },
    [],
  );

  const handleHostApplied = useCallback((next: DataAppConfig) => {
    setConfig(next);
    setSaveResult(null);
  }, []);

  async function handleSave(restart = false) {
    setSaving(true);
    setSaveResult(null);
    try {
      await api.setConfig(config);
      setSaveResult({
        type: "success",
        message: t("configure.saveSuccess"),
      });
      if (restart) {
        await paw.dependencies.action("context", "restart", {
          idempotencyKey: `context:restart:${Date.now()}`,
        });
        onRestart();
      }
    } catch (error) {
      setSaveResult({
        type: "error",
        message: errorMessage(error),
      });
    } finally {
      setSaving(false);
    }
  }

  async function runTest(target: "llm" | "embedding" | "neo4j") {
    setTesting((prev) => ({ ...prev, [target]: true }));
    // Drop the stale result instead of seeding a failure banner while the
    // request is still in flight.
    setTestResults((prev) => {
      if (!(target in prev)) return prev;
      const next = { ...prev };
      delete next[target];
      return next;
    });
    try {
      const result = await api.testConfig(target, config);
      setTestResults((prev) => ({ ...prev, [target]: result }));
    } catch (error) {
      setTestResults((prev) => ({
        ...prev,
        [target]: {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        },
      }));
    } finally {
      setTesting((prev) => ({ ...prev, [target]: false }));
    }
  }

  if (loading) {
    return (
      <section className="qwenpaw-data-configure">
        <div className="qwenpaw-data-configure__loading">
          {t("configure.loading")}
        </div>
      </section>
    );
  }

  return (
    <section className="qwenpaw-data-configure">
      {saveResult ? (
        <div
          className={`qwenpaw-data-configure__banner is-${saveResult.type}`}
          role="status"
        >
          {saveResult.message}
        </div>
      ) : null}

      <div className="qwenpaw-data-configure__sections">
        <section className="qwenpaw-data-configure__card">
          <div className="qwenpaw-data-configure__card-header">
            <h2>{t("configure.llm.title")}</h2>
            <p>{t("configure.llm.description")}</p>
          </div>
          <ReuseHostToggle
            api={api}
            target="llm"
            checked={config.llm.reuse_host}
            onApplied={handleHostApplied}
          />
          {config.llm.reuse_host ? (
            <div className="qwenpaw-data-configure__reuse-summary">
              <span className="qwenpaw-data-configure__reuse-summary-label">
                {t("configure.reuseHost.summaryLabel")}
              </span>
              <span className="qwenpaw-data-configure__reuse-summary-value">
                {config.llm.host_provider_name || config.llm.base_url}
                {" · "}
                {config.llm.model}
              </span>
            </div>
          ) : (
            <>
              <ProviderPresetSelect
                id="llm"
                baseUrl={config.llm.base_url}
                onSelect={(preset) =>
                  setSection("llm", {
                    ...config.llm,
                    provider: preset.id,
                    base_url: preset.baseUrl || config.llm.base_url,
                  })
                }
              />
              <ConfigFields
                values={config.llm}
                fields={[
                  { key: "base_url", label: t("configure.field.baseUrl") },
                  { key: "model", label: t("configure.field.model") },
                  {
                    key: "api_key",
                    label: t("configure.field.apiKey"),
                    type: "password",
                  },
                ]}
                onChange={(key, value) =>
                  setSection("llm", updateField(config.llm, key, value))
                }
              />
              <p className="qwenpaw-data-configure__ds-hint">
                {t("configure.openaiOnlyNote")}
              </p>
            </>
          )}
          <TestButton
            label={t("configure.test")}
            running={testing.llm}
            result={testResults.llm}
            onClick={() => void runTest("llm")}
          />
        </section>

        <section className="qwenpaw-data-configure__card">
          <div className="qwenpaw-data-configure__card-header">
            <h2>{t("configure.embedding.title")}</h2>
            <p>{t("configure.embedding.description")}</p>
          </div>
          <ReuseHostToggle
            api={api}
            target="embedding"
            checked={config.embedding.reuse_host}
            onApplied={handleHostApplied}
          />
          {config.embedding.reuse_host ? (
            <div className="qwenpaw-data-configure__reuse-summary">
              <span className="qwenpaw-data-configure__reuse-summary-label">
                {t("configure.reuseHost.embeddingSummaryLabel")}
              </span>
              <span className="qwenpaw-data-configure__reuse-summary-value">
                {config.embedding.host_provider_name ||
                  config.embedding.base_url}
              </span>
            </div>
          ) : (
            <ProviderPresetSelect
              id="embedding"
              baseUrl={config.embedding.base_url}
              onSelect={(preset) =>
                setSection("embedding", {
                  ...config.embedding,
                  base_url: preset.baseUrl || config.embedding.base_url,
                })
              }
            />
          )}
          {/* The host has no "active embedding model"; reuse shares its
              provider credentials while the model stays locally chosen. */}
          <ConfigFields
            values={config.embedding}
            fields={
              config.embedding.reuse_host
                ? [
                    { key: "model", label: t("configure.field.model") },
                    {
                      key: "dim",
                      label: t("configure.field.dimensions"),
                      type: "number",
                    },
                  ]
                : [
                    { key: "base_url", label: t("configure.field.baseUrl") },
                    { key: "model", label: t("configure.field.model") },
                    {
                      key: "api_key",
                      label: t("configure.field.apiKey"),
                      type: "password",
                    },
                    {
                      key: "dim",
                      label: t("configure.field.dimensions"),
                      type: "number",
                    },
                  ]
            }
            onChange={(key, value) =>
              setSection("embedding", updateField(config.embedding, key, value))
            }
          />
          <TestButton
            label={t("configure.test")}
            running={testing.embedding}
            result={testResults.embedding}
            onClick={() => void runTest("embedding")}
          />
        </section>

        <section className="qwenpaw-data-configure__card">
          <div className="qwenpaw-data-configure__card-header">
            <h2>{t("configure.neo4j.title")}</h2>
            <p>{t("configure.neo4j.description")}</p>
          </div>
          <ConfigFields
            values={config.neo4j}
            fields={[
              { key: "uri", label: t("configure.field.uri") },
              { key: "user", label: t("configure.field.user") },
              {
                key: "password",
                label: t("configure.field.password"),
                type: "password",
              },
              {
                key: "database",
                label: t("configure.field.database"),
                optional: true,
              },
            ]}
            onChange={(key, value) =>
              setSection("neo4j", updateField(config.neo4j, key, value))
            }
          />
          <TestButton
            label={t("configure.test")}
            running={testing.neo4j}
            result={testResults.neo4j}
            onClick={() => void runTest("neo4j")}
          />
        </section>
      </div>

      <div className="qwenpaw-data-configure__footer">
        <button
          type="button"
          className="qwenpaw-data-primary-button"
          disabled={saving}
          onClick={() => void handleSave(false)}
        >
          {saving ? t("configure.saving") : t("configure.save")}
        </button>
        <button
          type="button"
          className="qwenpaw-data-secondary-button"
          disabled={saving}
          onClick={() => void handleSave(true)}
        >
          {t("configure.saveAndRestart")}
        </button>
      </div>
    </section>
  );
}

function ConfigFields<T extends Record<string, string | number | boolean>>({
  values,
  fields,
  onChange,
}: {
  values: T;
  fields: Array<{
    key: keyof T;
    label: string;
    type?: "text" | "password" | "number";
    optional?: boolean;
  }>;
  onChange(key: keyof T, value: string | number | boolean): void;
}) {
  const t = useT();
  return (
    <div className="qwenpaw-data-configure__fields">
      {fields.map(({ key, label, type = "text", optional }) => (
        <div key={String(key)} className="qwenpaw-data-configure__field">
          <label htmlFor={`field-${String(key)}`}>
            {label}
            {optional ? (
              <span className="qwenpaw-data-configure__optional">
                {" "}
                {t("configure.optional")}
              </span>
            ) : null}
          </label>
          <input
            id={`field-${String(key)}`}
            type={type}
            value={String(values[key] ?? "")}
            onChange={(event) => {
              const raw = event.target.value;
              if (type === "number") {
                const num = Number(raw);
                onChange(key, Number.isNaN(num) ? 0 : num);
              } else {
                onChange(key, raw);
              }
            }}
          />
        </div>
      ))}
    </div>
  );
}

function TestButton({
  label,
  running,
  result,
  onClick,
}: {
  label: string;
  running: boolean;
  result?: ConnectionTestResult;
  onClick(): void;
}) {
  const t = useT();
  return (
    <div className="qwenpaw-data-configure__test-row">
      <button
        type="button"
        className="qwenpaw-data-secondary-button"
        disabled={running}
        onClick={onClick}
      >
        {running ? "…" : label}
      </button>
      {result ? (
        <span
          className={`qwenpaw-data-configure__test-result is-${
            result.ok ? "ok" : "error"
          }`}
        >
          {result.ok
            ? t("configure.testOk")
            : result.error || t("configure.testFailed")}
        </span>
      ) : null}
    </div>
  );
}
