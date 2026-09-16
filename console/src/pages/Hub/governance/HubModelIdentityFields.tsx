import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Form } from "antd";
import { RefreshCw } from "lucide-react";
import type { ModelInfo } from "../../../api/types";
import {
  governanceRequest,
  type ModelConnection,
  type ModelProviderPreset,
} from "../../../api/modules/hubGovernance";
import { ModelIdentityFields } from "../../Settings/Models/components/modals/ModelIdentityFields";
import styles from "./governance.module.less";

export function HubModelIdentityFields({
  connections,
  presets,
}: {
  connections: ModelConnection[];
  presets: ModelProviderPreset[];
}) {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const connectionId = Form.useWatch("connection_id", form);
  const connection = connections.find((c) => c.id === connectionId);
  const preset = presets.find((p) => p.id === connection?.provider_id);
  const [discovered, setDiscovered] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const requestId = useRef({ value: 0 });
  const load = useCallback(async () => {
    const current = ++requestId.current.value;
    setDiscovered([]);
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
      if (current === requestId.current.value) setDiscovered(models);
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
  const models = [
    ...new Map(
      [...(preset?.models ?? []), ...discovered].map((m) => [m.id, m]),
    ).values(),
  ];
  return (
    <>
      <ModelIdentityFields
        idField="upstream_model"
        nameLabel={t("hub.governance.models.memberDisplayName")}
        options={models.map((m) => ({
          value: m.id,
          label: `${m.name} · ${m.id}`,
        }))}
        loading={loading}
        onSelect={(id) => {
          const model = models.find((m) => m.id === id);
          form.setFieldsValue({
            name: model?.name || id,
            supports_image: model?.supports_image ?? false,
            input_token_limit:
              model?.max_input_length_auto_detected ?? model?.max_input_length,
            budget_verified: false,
          });
        }}
      />
      {connectionId && (
        <div className={styles.actions}>
          <Button
            size="small"
            icon={<RefreshCw size={14} />}
            loading={loading}
            onClick={load}
          >
            {t("hub.governance.models.refreshProviderModels")}
          </Button>
          <span className={styles.help} role={failed ? "status" : undefined}>
            {failed
              ? t("hub.governance.models.discoveryFailed")
              : t("hub.governance.models.chooseModel")}
          </span>
        </div>
      )}
    </>
  );
}
