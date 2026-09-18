import { host } from "./host";
import { recordingFeatureApi, type RecordingFeature } from "./api";
import { DesktopRecordingControl } from "./RecordingControl";
import { useTranslation } from "./locale";

const React = host.React;
const { Alert, Space, Switch, Typography, message } = host.antd;

export function RecordingSurface({ page = false }: { page?: boolean }) {
  const { t } = useTranslation();
  const [feature, setFeature] = React.useState<RecordingFeature | null>(null);
  const [error, setError] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const mutationEpoch = React.useRef(0);
  const mutating = React.useRef(false);
  React.useEffect(() => {
    let disposed = false;
    let refreshing = false;
    const refresh = async () => {
      if (refreshing || mutating.current) return;
      refreshing = true;
      const epoch = mutationEpoch.current;
      try {
        const value = await recordingFeatureApi.get();
        if (!disposed && epoch === mutationEpoch.current) {
          setFeature(value);
          setError(false);
        }
      } catch {
        if (!disposed && epoch === mutationEpoch.current) setError(true);
      } finally {
        refreshing = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);
  const toggle = async (enabled: boolean) => {
    mutationEpoch.current += 1;
    mutating.current = true;
    setBusy(true);
    try {
      setFeature(await recordingFeatureApi.set(enabled));
      setError(false);
    } catch {
      setError(true);
      message.error(t("desktop.recording.errors.generic"));
    } finally {
      mutating.current = false;
      setBusy(false);
    }
  };
  const controls =
    feature?.enabled && feature.supported_platform && !error ? (
      <DesktopRecordingControl />
    ) : null;
  if (!page) return controls;
  return (
    <Space direction="vertical" style={{ width: "100%", padding: 24 }}>
      <Typography.Title level={3}>Record & Replay</Typography.Title>
      <Typography.Paragraph>{t("feature.description")}</Typography.Paragraph>
      {error && (
        <Alert type="error" message={t("desktop.recording.errors.generic")} />
      )}
      {feature && !feature.supported_platform && (
        <Alert type="info" message={t("feature.platform")} />
      )}
      <Space>
        <Switch
          checked={feature?.enabled ?? false}
          loading={busy || feature === null}
          disabled={error || feature?.supported_platform !== true}
          aria-label={t("feature.enabled")}
          onChange={(value) => void toggle(value)}
        />
        {t("feature.enabled")}
      </Space>
      <Typography.Paragraph type="secondary">
        {t("feature.independence")}
      </Typography.Paragraph>
      {controls}
    </Space>
  );
}
