import React, {
  useCallback,
  useRef,
  useState,
  forwardRef,
  useImperativeHandle,
} from "react";
import { IconButton } from "@agentscope-ai/design";
import { SparkMicLine } from "@agentscope-ai/icons";
import { Tooltip, message } from "antd";
import { useTranslation } from "react-i18next";
import { agentApi } from "@/api/modules/agent";

export interface WhisperSpeechButtonRef {
  toggleRecording: () => void;
  isRecording: () => boolean;
  isLoading: () => boolean;
}

interface WhisperSpeechButtonProps {
  disabled?: boolean;
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

const WhisperSpeechButton = forwardRef<
  WhisperSpeechButtonRef,
  WhisperSpeechButtonProps
>(({ disabled }, ref) => {
  const { t } = useTranslation();
  const [recording, setRecording] = useState(false);
  const [loading, setLoading] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const internalRecordingRef = useRef(false);

  const setTextareaValue = useCallback(
    (textarea: HTMLTextAreaElement, value: string) => {
      const nativeValueSetter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      if (nativeValueSetter) {
        nativeValueSetter.call(textarea, value);
      } else {
        textarea.value = value;
      }
      textarea.selectionStart = textarea.selectionEnd = value.length;
      const event = new Event("input", { bubbles: true });
      textarea.dispatchEvent(event);
    },
    [],
  );

  const findTextarea = useCallback(() => {
    const senderContainer = document.querySelector('[class*="sender"]');
    return senderContainer?.querySelector(
      "textarea",
    ) as HTMLTextAreaElement | null;
  }, []);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && internalRecordingRef.current) {
      mediaRecorderRef.current.stop();
      internalRecordingRef.current = false;
      setRecording(false);
    }
  }, []);

  const startRecording = useCallback(async () => {
    if (internalRecordingRef.current || loading) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "audio/mp4";
      const recorder = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType });
        setLoading(true);
        try {
          const result = await agentApi.transcribeAudio(blob);
          if (result.text) {
            const textarea = findTextarea();
            if (textarea) {
              const currentValue = textarea.value || "";
              const newValue = currentValue
                ? `${currentValue} ${result.text}`
                : result.text;
              setTextareaValue(textarea, newValue);
              textarea.focus();
            }
          }
        } catch (err) {
          const errMsg =
            err instanceof Error ? err.message : "Transcription failed";
          if (errMsg.includes("Transcription is disabled")) {
            message.warning(t("chat.speech.transcriptionDisabled"));
          } else {
            message.error(t("chat.speech.transcriptionFailed"));
          }
          console.error("Transcription error:", err);
        } finally {
          setLoading(false);
        }
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      internalRecordingRef.current = true;
      setRecording(true);
    } catch (err) {
      console.error("Microphone access error:", err);
      message.error(t("chat.speech.microphoneError"));
    }
  }, [findTextarea, setTextareaValue, t, loading]);

  const toggleRecording = useCallback(() => {
    if (loading) return;
    if (internalRecordingRef.current) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [loading, startRecording, stopRecording]);

  // Expose methods via ref
  useImperativeHandle(
    ref,
    () => ({
      toggleRecording,
      isRecording: () => internalRecordingRef.current,
      isLoading: () => loading,
    }),
    [toggleRecording, loading],
  );

  const isDisabled = disabled || loading;

  return (
    <Tooltip
      title={
        loading
          ? t("chat.speech.transcribing")
          : recording
          ? t("chat.speech.stopRecording")
          : t("chat.speech.startRecording")
      }
      mouseEnterDelay={0.5}
    >
      <IconButton
        bordered={false}
        icon={loading || recording ? <RecordingIcon /> : <SparkMicLine />}
        onClick={toggleRecording}
        disabled={isDisabled}
        style={{
          color: recording || loading ? "#1890ff" : undefined,
        }}
      />
    </Tooltip>
  );
});

WhisperSpeechButton.displayName = "WhisperSpeechButton";

export default WhisperSpeechButton;
