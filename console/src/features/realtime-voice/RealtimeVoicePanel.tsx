import {
  AudioMutedOutlined,
  AudioOutlined,
  PauseCircleOutlined,
  PhoneOutlined,
  SettingOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Alert, Button, Modal, Select, Tooltip, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { buildChatPath } from "../../utils/sessionRoute";
import { useAgentStore } from "../../stores/agentStore";
import { isRealtimeVoiceActive, useRealtimeVoice } from "./useRealtimeVoice";
import styles from "./realtimeVoice.module.less";

export type RealtimeVoiceController = ReturnType<typeof useRealtimeVoice>;

function configurationMessage(
  voice: RealtimeVoiceController,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  return (
    voice.capabilities?.configuration_error?.message ||
    t("realtimeVoice.credentialMissing")
  );
}

export function RealtimeVoiceConflictModal({
  voice,
}: {
  voice: RealtimeVoiceController;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setSelectedAgent = useAgentStore((state) => state.setSelectedAgent);

  const openActiveChat = () => {
    const activeChatId = voice.conflict?.chatId;
    if (!activeChatId) return;
    if (voice.conflict?.agentId) setSelectedAgent(voice.conflict.agentId);
    navigate(buildChatPath(activeChatId));
  };

  return (
    <Modal
      open={Boolean(voice.conflict)}
      title={t("realtimeVoice.switchTitle")}
      okText={t("realtimeVoice.switchConfirm")}
      cancelText={t("common.cancel")}
      onOk={() => void voice.confirmSwitch()}
      onCancel={voice.cancelSwitch}
    >
      <Typography.Paragraph>
        {t("realtimeVoice.switchDescription")}
      </Typography.Paragraph>
      {voice.conflict && (
        <Typography.Paragraph type="secondary">
          {t("realtimeVoice.activeSessionSummary", {
            agentId: voice.conflict.agentId || "—",
            chatId: voice.conflict.chatId || "—",
          })}
        </Typography.Paragraph>
      )}
      {voice.conflict?.chatId && (
        <Button onClick={openActiveChat}>
          {t("realtimeVoice.openActiveChat")}
        </Button>
      )}
    </Modal>
  );
}

export function RealtimeVoiceControls({
  voice,
  canStart = true,
}: {
  voice: RealtimeVoiceController;
  canStart?: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const active = isRealtimeVoiceActive(voice.status);
  const ready = voice.readyToStart;
  const assistantTurn =
    voice.status === "assistant_speaking" && voice.assistantTranscript;
  const userTurn = voice.status === "user_speaking" && voice.inputTranscript;
  const liveText = assistantTurn ? voice.assistantTranscript : userTurn || "";
  const liveRole = assistantTurn
    ? t("realtimeVoice.assistant")
    : t("realtimeVoice.you");

  return (
    <div className={styles.controlArea}>
      <div
        className={`${styles.voiceDock} ${
          active ? styles.voiceDockActive : ""
        } ${voice.status === "error" ? styles.voiceDockError : ""}`}
      >
        <div className={styles.statusSummary} aria-live="polite">
          <div
            className={`${styles.statusIcon} ${styles[voice.status]}`}
            aria-hidden="true"
          >
            {voice.status === "assistant_speaking" ? (
              <PhoneOutlined />
            ) : voice.muted ? (
              <AudioMutedOutlined />
            ) : (
              <AudioOutlined />
            )}
          </div>
          <div className={styles.statusCopy}>
            <div className={styles.statusHeading}>
              <Typography.Text strong>
                {t(`realtimeVoice.status.${voice.status}`)}
              </Typography.Text>
            </div>
            {liveText ? (
              <Typography.Text
                type="secondary"
                className={styles.liveTranscript}
                aria-live="polite"
                title={`${liveRole} ${liveText}`}
              >
                <span>{liveRole}</span>
                {liveText}
              </Typography.Text>
            ) : (
              <Typography.Text type="secondary" className={styles.statusHint}>
                {voice.status === "connecting"
                  ? t("realtimeVoice.connectingHint")
                  : active
                  ? t("realtimeVoice.liveHint")
                  : t("realtimeVoice.resumeHint")}
              </Typography.Text>
            )}
          </div>
        </div>

        <div className={styles.actions}>
          {!active ? (
            <Button
              type="primary"
              size="large"
              className={styles.primaryAction}
              icon={<AudioOutlined />}
              aria-label={t("realtimeVoice.resume")}
              loading={voice.status === "connecting"}
              disabled={!ready || !canStart}
              onClick={() => {
                if (canStart) voice.start();
              }}
            >
              {t("realtimeVoice.resume")}
            </Button>
          ) : (
            <>
              {voice.inputDevices.length > 0 && (
                <Select
                  className={styles.deviceSelect}
                  value={voice.inputDeviceId}
                  aria-label={t("realtimeVoice.microphone")}
                  options={[
                    {
                      value: "",
                      label: t("realtimeVoice.defaultMicrophone"),
                    },
                    ...voice.inputDevices.map((device, index) => ({
                      value: device.deviceId,
                      label:
                        device.label ||
                        `${t("realtimeVoice.microphone")} ${index + 1}`,
                    })),
                  ]}
                  onChange={(deviceId) => void voice.setInputDevice(deviceId)}
                />
              )}
              <Button
                className={styles.secondaryAction}
                icon={voice.muted ? <AudioMutedOutlined /> : <AudioOutlined />}
                aria-label={
                  voice.muted
                    ? t("realtimeVoice.unmute")
                    : t("realtimeVoice.mute")
                }
                onClick={() => voice.setMuted(!voice.muted)}
              >
                {voice.muted
                  ? t("realtimeVoice.unmute")
                  : t("realtimeVoice.mute")}
              </Button>
              <Button
                className={styles.secondaryAction}
                icon={<PauseCircleOutlined />}
                aria-label={t("realtimeVoice.interrupt")}
                disabled={voice.outputState !== "speaking"}
                onClick={voice.interrupt}
              >
                {t("realtimeVoice.interrupt")}
              </Button>
              <Button
                danger
                className={styles.stopAction}
                icon={<StopOutlined />}
                aria-label={t("realtimeVoice.stop")}
                onClick={() => void voice.stop()}
              >
                {t("realtimeVoice.stop")}
              </Button>
            </>
          )}
          <Tooltip title={t("realtimeVoice.settings")}>
            <Button
              type="text"
              shape="circle"
              className={styles.settingsAction}
              icon={<SettingOutlined />}
              aria-label={t("realtimeVoice.settings")}
              onClick={() =>
                navigate(
                  `/models?realtimeVoice=1${
                    voice.capabilities?.active_model?.provider_id
                      ? `&provider=${encodeURIComponent(
                          voice.capabilities.active_model.provider_id,
                        )}`
                      : ""
                  }`,
                )
              }
            />
          </Tooltip>
        </div>
      </div>

      {!ready && voice.capabilities && !active && (
        <Alert
          className={styles.alert}
          type="warning"
          showIcon
          message={configurationMessage(voice, t)}
          action={
            <Button
              size="small"
              onClick={() => navigate("/models?realtimeVoice=1")}
            >
              {t("realtimeVoice.configure")}
            </Button>
          }
        />
      )}

      {voice.error && (
        <Alert
          className={styles.alert}
          type="error"
          showIcon
          closable
          message={voice.error}
        />
      )}

      {voice.pendingInputError && active && (
        <Alert
          className={styles.alert}
          type="warning"
          showIcon
          message={voice.pendingInputError}
        />
      )}
    </div>
  );
}
