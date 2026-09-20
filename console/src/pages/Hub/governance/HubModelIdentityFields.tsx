import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Form, Input, Skeleton } from "antd";
import { RefreshCw } from "lucide-react";
import type { ModelInfo } from "../../../api/types";
import {
  governanceRequest,
  type ManagedModel,
  type ModelConnection,
  type ModelProviderPreset,
} from "../../../api/modules/hubGovernance";
import { ModelIdentityFields } from "../../Settings/Models/components/modals/ModelIdentityFields";
import { CapabilityTags } from "../../Settings/Models/components/modals/ModelCapabilityTags";
import {
  ContextLengthField,
  OutputTokenLimitField,
} from "../../Settings/Models/components/modals/ModelTokenFields";
import styles from "./governance.module.less";

export function HubModelIdentityFields({
  connections,
  presets,
  saved,
}: {
  connections: ModelConnection[];
  presets: ModelProviderPreset[];
  saved?: ManagedModel;
}) {
  const { t, i18n } = useTranslation();
  const form = Form.useFormInstance();
  const connectionId = Form.useWatch("connection_id", form);
  const modelId = Form.useWatch("upstream_model", form);
  const inputLimit = Form.useWatch("input_token_limit", form);
  const outputLimit = Form.useWatch("output_token_limit", form);
  const connection = connections.find((c) => c.id === connectionId);
  const preset = presets.find((p) => p.id === connection?.provider_id);
  const [directory, setDirectory] = useState<{
    connectionId: string;
    models: ModelInfo[];
  }>();
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const requestId = useRef({ value: 0 });
  const load = useCallback(async () => {
    const current = ++requestId.current.value;
    setFailed(false);
    if (!connectionId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const models = await governanceRequest<ModelInfo[]>(
        `admin/model-connections/${connectionId}/discover`,
        "POST",
      );
      if (current === requestId.current.value)
        setDirectory({ connectionId, models });
    } catch {
      if (current === requestId.current.value) setFailed(true);
    } finally {
      if (current === requestId.current.value) setLoading(false);
    }
  }, [connectionId]);
  useEffect(() => {
    void load();
    const tracker = requestId.current;
    return () => {
      tracker.value++;
    };
  }, [load]);
  // The server uses the same catalog merge as personal providers.
  const models =
    directory && directory.connectionId === connectionId
      ? directory.models
      : preset?.models ?? [];
  const model = models.find((m) => m.id === modelId);
  const identity = `${connectionId ?? ""}:${modelId ?? ""}`;
  const [defaults, setDefaults] = useState<{
    identity: string;
    input_token_limit: number;
    output_token_limit: number | null;
    input_limit_known: boolean;
    output_limit_known: boolean;
  }>();
  useEffect(() => {
    if (!connectionId || !modelId) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void governanceRequest<Omit<NonNullable<typeof defaults>, "identity">>(
        `admin/model-connections/${connectionId}/token-defaults?model_id=${encodeURIComponent(
          modelId,
        )}`,
      )
        .then((value) => {
          if (!cancelled) setDefaults({ ...value, identity });
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        });
    }, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [connectionId, modelId, identity]);
  const resolved = defaults?.identity === identity ? defaults : undefined;
  const inputDefault =
    model?.max_input_length_auto_detected ?? resolved?.input_token_limit;
  const outputDefault =
    model?.max_output_length ?? resolved?.output_token_limit ?? null;
  const knownInput =
    model?.max_input_length_auto_detected ??
    (resolved?.input_limit_known ? inputDefault : undefined);
  const knownOutput =
    model?.max_output_length ??
    (resolved?.output_limit_known ? outputDefault ?? undefined : undefined);
  const automatic = useRef<{
    identity: string;
    input?: number;
    output?: number | null;
    name: string;
  }>();
  useEffect(() => {
    const previous = automatic.current;
    const changed = previous?.identity !== identity;
    const original =
      saved &&
      saved.connection_id === connectionId &&
      saved.upstream_model === modelId
        ? saved
        : undefined;
    const input = changed
      ? original?.input_token_limit
      : form.getFieldValue("input_token_limit");
    const output = changed
      ? original?.output_token_limit
      : form.getFieldValue("output_token_limit");
    const name = changed ? original?.name : form.getFieldValue("name");
    form.setFieldsValue({
      input_token_limit:
        input == null || (!changed && input === previous?.input)
          ? inputDefault
          : input,
      output_token_limit:
        output == null || (!changed && output === previous?.output)
          ? outputDefault
          : output,
      supports_image: model?.supports_image ?? original?.supports_image ?? null,
      name:
        !name || (!changed && name === previous?.name)
          ? model?.name || modelId
          : name,
    });
    automatic.current = {
      identity,
      input: inputDefault,
      output: outputDefault,
      name: model?.name || modelId,
    };
  }, [
    identity,
    connectionId,
    modelId,
    inputDefault,
    outputDefault,
    model?.name,
    model?.supports_image,
    saved,
    form,
  ]);
  const savedImage =
    saved &&
    saved.connection_id === connectionId &&
    saved.upstream_model === modelId
      ? saved.supports_image
      : null;
  const capabilityModel = useMemo(
    () =>
      ({
        ...model,
        supports_image: model?.supports_image ?? savedImage ?? null,
        supports_multimodal:
          model?.supports_multimodal ?? model?.supports_image ?? null,
        supports_video: false,
      }) as ModelInfo,
    [model, savedImage],
  );
  return (
    <>
      <ModelIdentityFields
        idField="upstream_model"
        idSuffix={
          <Button
            type="text"
            size="small"
            disabled={!connectionId}
            loading={loading}
            aria-label={t("hub.governance.models.refreshProviderModels")}
            icon={<RefreshCw size={14} />}
            onClick={load}
          />
        }
        nameLabel={t("hub.governance.models.memberDisplayName")}
        options={models.map((m) => ({
          value: m.id,
          label: m.name === m.id ? m.id : `${m.name} · ${m.id}`,
        }))}
        loading={loading}
      />
      {failed && (
        <div role="alert" className={styles.catalogStatus}>
          {t("hub.governance.models.discoveryFailed")}
        </div>
      )}
      {modelId && (
        <div className={styles.capabilities}>
          <div className={styles.heading}>
            <strong>{t("hub.governance.models.capabilities")}</strong>
            <CapabilityTags model={capabilityModel} />
          </div>
          <dl className={styles.capabilityValues}>
            <div>
              <dt>{t("models.maxInputLengthLabel")}</dt>
              <dd>
                {inputDefault?.toLocaleString(i18n.language) ??
                  t("models.unknown")}
              </dd>
            </div>
            <div>
              <dt>{t("models.maxTokensLabel")}</dt>
              <dd>
                {outputDefault?.toLocaleString(i18n.language) ??
                  t("models.unknown")}
              </dd>
            </div>
          </dl>
          {resolved && (!knownInput || !knownOutput) && (
            <div role="note" className={styles.catalogStatus}>
              {t("hub.governance.models.estimatedTokenLimits")}
            </div>
          )}
          {loading && !model ? (
            <Skeleton active paragraph={{ rows: 1 }} title={false} />
          ) : (
            (!knownInput || !knownOutput) && (
              <div className={styles.missingCapabilities}>
                {!knownInput && (
                  <ContextLengthField
                    showHint={false}
                    value={inputLimit ?? null}
                    onChange={(value) =>
                      form.setFieldValue("input_token_limit", value)
                    }
                  />
                )}
                {!knownOutput && (
                  <OutputTokenLimitField
                    showHint={false}
                    value={outputLimit ?? null}
                    onChange={(value) =>
                      form.setFieldValue("output_token_limit", value)
                    }
                    model={model}
                  />
                )}
              </div>
            )
          )}
        </div>
      )}
      <Form.Item
        name="input_token_limit"
        hidden
        rules={[
          {
            required: true,
            type: "number",
            min: 1000,
            max: knownInput ?? 10000000,
            message: t("hub.governance.models.completeCapabilities"),
          },
        ]}
      >
        <Input />
      </Form.Item>
      <Form.Item
        name="output_token_limit"
        hidden
        rules={[
          {
            type: "number",
            min: 1,
            max: knownOutput ?? 1000000,
            message: t("hub.governance.models.completeCapabilities"),
          },
        ]}
      >
        <Input />
      </Form.Item>
      <Form.Item name="supports_image" hidden>
        <Input />
      </Form.Item>
      {modelId && !!knownOutput && (
        <details className={styles.advancedSettings}>
          <summary>{t("hub.governance.models.responseLimit")}</summary>
          <OutputTokenLimitField
            showHint={false}
            model={{ ...model, max_output_length: knownOutput }}
            value={outputLimit === knownOutput ? null : outputLimit ?? null}
            onChange={(value) =>
              form.setFieldValue("output_token_limit", value ?? knownOutput)
            }
          />
        </details>
      )}
    </>
  );
}
