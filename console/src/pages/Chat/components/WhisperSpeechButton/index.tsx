import React, { forwardRef, useImperativeHandle, useRef } from "react";
import { IconButton } from "@agentscope-ai/design";
import { SparkMicLine } from "@agentscope-ai/icons";
import { Tooltip, Button } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useVoiceInput, type VoiceInputProps } from "./useVoiceInput";

export interface WhisperSpeechButtonRef {
  toggleRecording: () => void;
  isRecording: () => boolean;
  isLoading: () => boolean;
}
// Original recording icon animation from @agentscope-ai/chat
const SIZE = 1000;
const COUNT = 4;
const RECT_WIDTH = 140;
const RECT_RADIUS = RECT_WIDTH / 2;
const RECT_HEIGHT_MIN = 250;
const RECT_HEIGHT_MAX = 500;
const DURATION = 0.8;

const RecordingIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox={`0 0 ${SIZE} ${SIZE}`}
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{
      color: "#1890ff",
      height: "1.2em",
      width: "1.2em",
      verticalAlign: "top",
    }}
  >
    <title>Speech Recording</title>
    {Array.from({ length: COUNT }).map((_, index) => {
      const dest = (SIZE - RECT_WIDTH * COUNT) / (COUNT - 1);
      const x = index * (dest + RECT_WIDTH);
      const yMin = SIZE / 2 - RECT_HEIGHT_MIN / 2;
      const yMax = SIZE / 2 - RECT_HEIGHT_MAX / 2;

      return (
        <rect
          fill="currentColor"
          rx={RECT_RADIUS}
          ry={RECT_RADIUS}
          height={RECT_HEIGHT_MIN}
          width={RECT_WIDTH}
          x={x}
          y={yMin}
          key={index}
        >
          <animate
            attributeName="height"
            values={`${RECT_HEIGHT_MIN}; ${RECT_HEIGHT_MAX}; ${RECT_HEIGHT_MIN}`}
            keyTimes="0; 0.5; 1"
            dur={`${DURATION}s`}
            begin={`${(DURATION / COUNT) * index}s`}
            repeatCount="indefinite"
          />
          <animate
            attributeName="y"
            values={`${yMin}; ${yMax}; ${yMin}`}
            keyTimes="0; 0.5; 1"
            dur={`${DURATION}s`}
            begin={`${(DURATION / COUNT) * index}s`}
            repeatCount="indefinite"
          />
        </rect>
      );
    })}
  </svg>
);

const WhisperSpeechButton = forwardRef<WhisperSpeechButtonRef, VoiceInputProps>(
  (props, ref) => {
    const { t } = useTranslation();
    const root = useRef<HTMLSpanElement>(null);
    const voice = useVoiceInput({
      ...props,
      getSender: props.getSender
        ? () => props.getSender!(root.current)
        : undefined,
    });
    const file = useRef<HTMLInputElement>(null);
    const recording = voice.phase === "recording";
    const busy = voice.phase !== "idle";
    const loading = busy && !recording;
    useImperativeHandle(ref, () => ({
      toggleRecording: () => {
        void voice.toggleRecording();
      },
      isRecording: () => recording,
      isLoading: () => loading,
    }));
    const label = t(
      recording ? "chat.speech.stopRecording" : "chat.speech.startRecording",
    );
    return (
      <span ref={root}>
        <Tooltip title={label}>
          <IconButton
            bordered={false}
            aria-label={label}
            data-testid="voice-record"
            icon={
              loading ? (
                <LoadingOutlined />
              ) : recording ? (
                <RecordingIcon />
              ) : (
                <SparkMicLine />
              )
            }
            disabled={voice.disabled || loading}
            onClick={() => {
              void voice.toggleRecording();
            }}
          />
        </Tooltip>
        <Button
          type="text"
          aria-label={t("chat.speech.uploadAudio")}
          data-testid="voice-upload-button"
          disabled={voice.disabled || busy}
          onClick={() => file.current?.click()}
        >
          {t("chat.speech.uploadAudio")}
        </Button>
        <input
          ref={file}
          hidden
          type="file"
          accept="audio/*"
          aria-label={t("chat.speech.uploadAudio")}
          data-testid="voice-upload-input"
          disabled={voice.disabled || busy}
          onChange={(e) => {
            const selected = e.target.files?.[0];
            e.target.value = "";
            if (selected) voice.upload(selected);
          }}
        />
        {busy && (
          <Button
            type="text"
            aria-label={t("chat.speech.cancel")}
            data-testid="voice-cancel"
            onClick={voice.cancel}
          >
            {t("chat.speech.cancel")}
          </Button>
        )}
      </span>
    );
  },
);
WhisperSpeechButton.displayName = "WhisperSpeechButton";
export default WhisperSpeechButton;
