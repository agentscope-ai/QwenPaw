import { Alert, Button, Descriptions, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { LocalWhisperStatus } from "../useVoiceTranscription";

export function LocalWhisperCard({
  status,
  onInstall,
  onEnable,
}: {
  status: LocalWhisperStatus;
  onInstall?: () => void;
  onEnable?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const preparing = status.state === "installing";
  const repair =
    status.plugin_installed &&
    (!status.whisper_installed ||
      status.state === "failed" ||
      status.state === "inactive");
  const canInstall = !status.plugin_installed || repair || preparing;
  const installedText = (installed: boolean) =>
    t(
      `voiceTranscription.localWhisperDependency_${
        installed ? "installed" : "missing"
      }`,
    );

  return (
    <section style={{ marginTop: 16 }} aria-label="Local Whisper">
      <Alert
        showIcon
        type={
          preparing
            ? "info"
            : status.available
            ? "success"
            : status.error
            ? "error"
            : "warning"
        }
        message={t(`voiceTranscription.localWhisperState_${status.state}`)}
        description={
          status.error ||
          (status.available
            ? t("voiceTranscription.localWhisperModelHint")
            : status.state === "missing" && status.whisper_installed
            ? t("voiceTranscription.localWhisperDependenciesKept")
            : undefined)
        }
      />
      <Descriptions column={1} size="small" style={{ marginTop: 16 }}>
        <Descriptions.Item label={t("voiceTranscription.localWhisperPlugin")}>
          {t(
            `voiceTranscription.localWhisperPlugin_${
              !status.plugin_installed
                ? "missing"
                : !status.plugin_enabled
                ? "disabled"
                : status.plugin_status
            }`,
          )}
        </Descriptions.Item>
        <Descriptions.Item label="openai-whisper">
          {installedText(status.whisper_installed)}
        </Descriptions.Item>
        <Descriptions.Item label="ffmpeg">
          {installedText(status.ffmpeg_installed)}
        </Descriptions.Item>
      </Descriptions>
      <Space wrap style={{ marginTop: 12 }}>
        {canInstall && (
          <Button type="primary" loading={preparing} onClick={onInstall}>
            {t(
              repair || status.error
                ? "common.retry"
                : "voiceTranscription.localWhisperInstall",
            )}
          </Button>
        )}
        {status.plugin_installed && !status.plugin_enabled && !preparing && (
          <Button type={canInstall ? "default" : "primary"} onClick={onEnable}>
            {t("voiceTranscription.localWhisperEnable")}
          </Button>
        )}
        {!status.ffmpeg_installed && (
          <Typography.Link
            href="https://ffmpeg.org/download.html"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("voiceTranscription.localWhisperFfmpegHelp")}
          </Typography.Link>
        )}
        {status.plugin_installed && (
          <Button onClick={() => navigate("/market?tab=plugins")}>
            {t("voiceTranscription.localWhisperManage")}
          </Button>
        )}
      </Space>
      {!status.ffmpeg_installed && (
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
          {t("voiceTranscription.localWhisperFfmpegHint")}
        </Typography.Paragraph>
      )}
    </section>
  );
}
