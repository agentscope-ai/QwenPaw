import { useEffect, useState } from "react";
import { Button, Card } from "@agentscope-ai/design";
import { Switch, InputNumber, Input, Slider, Spin, Alert } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import styles from "./index.module.less";

interface SemanticRoutingSettings {
  enabled: boolean;
  encoder: string;
  top_k: number;
  min_score: number;
  max_tools: number;
  token_budget: number;
}

const DEFAULTS: SemanticRoutingSettings = {
  enabled: false,
  encoder: "all-MiniLM-L6-v2",
  top_k: 10,
  min_score: 0.0,
  max_tools: 20,
  token_budget: 8000,
};

function SemanticRoutingPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] =
    useState<SemanticRoutingSettings>(DEFAULTS);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const res = await api.getConfig();
      const sr = res?.semantic_routing ?? {};
      setSettings({ ...DEFAULTS, ...sr });
    } catch (err) {
      console.error("Failed to load semantic routing settings:", err);
      message.error(t("semanticRouting.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateConfig({ semantic_routing: settings });
      message.success(t("semanticRouting.saveSuccess"));
    } catch (err) {
      console.error("Failed to save semantic routing settings:", err);
      message.error(t("semanticRouting.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const update = (patch: Partial<SemanticRoutingSettings>) =>
    setSettings((prev) => ({ ...prev, ...patch }));

  if (loading) {
    return (
      <div className={styles.semanticRoutingPage}>
        <div className={styles.centerState}>
          <Spin />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.semanticRoutingPage}>
      <PageHeader
        items={[
          { title: t("nav.settings") },
          { title: t("semanticRouting.title") },
        ]}
      />

      <div className={styles.content}>
        {/* Enable / Disable */}
        <Card className={styles.card}>
          <h3 className={styles.cardTitle}>
            {t("semanticRouting.enableLabel")}
          </h3>
          <p className={styles.cardDescription}>
            {t("semanticRouting.enableDescription")}
          </p>
          <Switch
            checked={settings.enabled}
            onChange={(checked) => update({ enabled: checked })}
          />
          {settings.enabled && (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message={t("semanticRouting.depsHint")}
            />
          )}
        </Card>

        {settings.enabled && (
          <>
            {/* Encoder */}
            <Card className={styles.card}>
              <h3 className={styles.cardTitle}>
                {t("semanticRouting.encoderLabel")}
              </h3>
              <p className={styles.cardDescription}>
                {t("semanticRouting.encoderDescription")}
              </p>
              <Input
                value={settings.encoder}
                onChange={(e) => update({ encoder: e.target.value })}
                placeholder="all-MiniLM-L6-v2"
                style={{ maxWidth: 400 }}
              />
            </Card>

            {/* Top-K */}
            <Card className={styles.card}>
              <h3 className={styles.cardTitle}>
                {t("semanticRouting.topKLabel")}
              </h3>
              <p className={styles.cardDescription}>
                {t("semanticRouting.topKDescription")}
              </p>
              <div className={styles.fieldRow}>
                <Slider
                  min={1}
                  max={50}
                  value={settings.top_k}
                  onChange={(val) => update({ top_k: val })}
                  style={{ flex: 1, maxWidth: 300 }}
                />
                <InputNumber
                  min={1}
                  max={50}
                  value={settings.top_k}
                  onChange={(val) => update({ top_k: val ?? 10 })}
                />
              </div>
            </Card>

            {/* Min Score */}
            <Card className={styles.card}>
              <h3 className={styles.cardTitle}>
                {t("semanticRouting.minScoreLabel")}
              </h3>
              <p className={styles.cardDescription}>
                {t("semanticRouting.minScoreDescription")}
              </p>
              <div className={styles.fieldRow}>
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={settings.min_score}
                  onChange={(val) => update({ min_score: val })}
                  style={{ flex: 1, maxWidth: 300 }}
                />
                <InputNumber
                  min={0}
                  max={1}
                  step={0.05}
                  value={settings.min_score}
                  onChange={(val) => update({ min_score: val ?? 0 })}
                />
              </div>
            </Card>
          </>
        )}
      </div>

      <div className={styles.footerButtons}>
        <Button
          onClick={fetchSettings}
          disabled={saving}
          style={{ marginRight: 8 }}
        >
          {t("common.reset")}
        </Button>
        <Button type="primary" onClick={handleSave} loading={saving}>
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export default SemanticRoutingPage;
