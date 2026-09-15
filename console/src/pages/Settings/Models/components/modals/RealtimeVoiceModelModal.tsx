import { useEffect, useMemo, useState } from "react";
import { Form, Input, InputNumber, Modal, Select } from "antd";
import { useTranslation } from "react-i18next";
import type {
  ProviderInfo,
  RealtimeVoiceModelConfig,
} from "../../../../../api/types";
import { providerApi } from "../../../../../api/modules/provider";
import { useAppMessage } from "../../../../../hooks/useAppMessage";

interface Props {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

type FormValues = Omit<RealtimeVoiceModelConfig, "id" | "name" | "vad"> & {
  vad_mode: string;
  vad_threshold: number;
  vad_silence_duration_ms: number;
};

function valuesFor(model: RealtimeVoiceModelConfig): FormValues {
  return {
    region: model.region,
    realtime_model: model.realtime_model,
    endpoint: model.endpoint,
    voice: model.voice,
    language: model.language,
    vad_mode: model.vad.mode,
    vad_threshold: model.vad.threshold,
    vad_silence_duration_ms: model.vad.silence_duration_ms,
    continuation_grace_ms: model.continuation_grace_ms,
    presentation_capacity: model.presentation_capacity,
    playback_timeout_seconds: model.playback_timeout_seconds,
    max_history_turns: model.max_history_turns,
    max_session_seconds: model.max_session_seconds,
  };
}

export function RealtimeVoiceModelModal({
  provider,
  open,
  onClose,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [form] = Form.useForm<FormValues>();
  const [modelId, setModelId] = useState(provider.realtime_models[0]?.id || "");
  const [saving, setSaving] = useState(false);
  const capability = provider.realtime_voice;
  const selectedModel = useMemo(
    () => provider.realtime_models.find((model) => model.id === modelId),
    [modelId, provider.realtime_models],
  );

  useEffect(() => {
    const next =
      provider.realtime_models.find((model) => model.id === modelId) ||
      provider.realtime_models[0];
    if (!next) return;
    setModelId(next.id);
    form.setFieldsValue(valuesFor(next));
  }, [form, modelId, provider.realtime_models]);

  const save = async (values: FormValues) => {
    if (!selectedModel) return;
    setSaving(true);
    try {
      await providerApi.configureRealtimeVoiceModel(provider.id, modelId, {
        region: values.region,
        realtime_model: values.realtime_model,
        endpoint: values.endpoint?.trim() || null,
        voice: values.voice.trim(),
        language: values.language.trim(),
        vad: {
          mode: values.vad_mode,
          threshold: values.vad_threshold,
          silence_duration_ms: values.vad_silence_duration_ms,
        },
        continuation_grace_ms: values.continuation_grace_ms,
        presentation_capacity: values.presentation_capacity,
        playback_timeout_seconds: values.playback_timeout_seconds,
        max_history_turns: values.max_history_turns,
        max_session_seconds: values.max_session_seconds,
      });
      message.success(t("realtimeVoice.saved"));
      await onSaved();
      onClose();
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`${provider.name} · ${t("realtimeVoice.settings")}`}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={saving}
      destroyOnHidden
      width={720}
    >
      <Form<FormValues> form={form} layout="vertical" onFinish={save}>
        <Form.Item label={t("realtimeVoice.model")} required>
          <Select
            value={modelId}
            options={provider.realtime_models.map((model) => ({
              value: model.id,
              label: `${model.name} (${model.id})`,
            }))}
            onChange={setModelId}
          />
        </Form.Item>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            gap: "0 20px",
          }}
        >
          <Form.Item
            name="region"
            label={t("realtimeVoice.region")}
            rules={[{ required: true }]}
          >
            <Select
              options={(capability?.regions || []).map((region) => ({
                value: region.id,
                label: region.label,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="realtime_model"
            label={t("realtimeVoice.speechModel")}
            rules={[{ required: true }]}
          >
            <Select
              options={(capability?.speech_models || []).map((model) => ({
                value: model.id,
                label: model.label,
              }))}
            />
          </Form.Item>
          <Form.Item name="endpoint" label={t("realtimeVoice.endpoint")}>
            <Input placeholder="wss://" />
          </Form.Item>
          <Form.Item
            name="voice"
            label={t("realtimeVoice.voice")}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="language"
            label={t("realtimeVoice.language")}
            extra={t("realtimeVoice.languageHelp")}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input placeholder="zh-CN" />
          </Form.Item>
          <Form.Item
            name="vad_mode"
            label={t("realtimeVoice.vadMode")}
            rules={[{ required: true }]}
          >
            <Select
              options={(capability?.vad_modes || []).map((mode) => ({
                value: mode,
                label: mode,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="vad_threshold"
            label={t("realtimeVoice.vadThreshold")}
            rules={[{ required: true }]}
          >
            <InputNumber
              min={-1}
              max={1}
              step={0.05}
              style={{ width: "100%" }}
            />
          </Form.Item>
          <Form.Item
            name="vad_silence_duration_ms"
            label={t("realtimeVoice.silenceDuration")}
            rules={[{ required: true }]}
          >
            <InputNumber
              min={200}
              max={6000}
              step={100}
              addonAfter="ms"
              style={{ width: "100%" }}
            />
          </Form.Item>
          <Form.Item
            name="max_history_turns"
            label={t("realtimeVoice.maxHistoryTurns")}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={50} step={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name="continuation_grace_ms"
            label={t("realtimeVoice.continuationGrace")}
            tooltip={t("realtimeVoice.continuationGraceHelp")}
            rules={[{ required: true }]}
          >
            <InputNumber
              min={0}
              max={5000}
              step={100}
              addonAfter="ms"
              style={{ width: "100%" }}
            />
          </Form.Item>
          <Form.Item
            name="max_session_seconds"
            label={t("realtimeVoice.maxSession")}
            rules={[{ required: true }]}
          >
            <InputNumber
              min={60}
              max={14400}
              step={60}
              addonAfter="s"
              style={{ width: "100%" }}
            />
          </Form.Item>
          <Form.Item
            name="presentation_capacity"
            label={t("realtimeVoice.presentationCapacity")}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={128} step={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name="playback_timeout_seconds"
            label={t("realtimeVoice.playbackTimeout")}
            rules={[{ required: true }]}
          >
            <InputNumber
              min={10}
              max={300}
              step={10}
              addonAfter="s"
              style={{ width: "100%" }}
            />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
