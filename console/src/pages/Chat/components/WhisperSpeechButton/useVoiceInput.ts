import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { useVoiceScope } from "@/api/voiceScope";
import {
  voiceApi,
  TranscriptionError,
  transcriptionErrorKey,
} from "@/api/modules/voice";
import { useUploadLimitStore } from "@/stores/uploadLimitStore";

export interface VoiceInputProps {
  disabled?: boolean;
  conversationId?: string | null;
  contextKey?: string;
  getSender?: (anchor?: HTMLElement | null) => HTMLTextAreaElement | null;
  onTranscription: (text: string, sender?: HTMLTextAreaElement) => void;
}
interface Operation {
  controller: AbortController;
  current: () => boolean;
  sender?: HTMLTextAreaElement;
  recorder?: MediaRecorder;
  stream?: MediaStream;
  timer?: ReturnType<typeof setTimeout>;
}
export function useVoiceInput(props: VoiceInputProps) {
  const scope = useVoiceScope();
  const { t } = useTranslation();
  const latest = useRef(props);
  latest.current = props;
  const [phase, setPhase] = useState<
    "idle" | "microphone" | "recording" | "transcribing"
  >("idle");
  const operation = useRef<Operation | null>(null);
  const mounted = useRef(false);
  const release = (op: Operation) => {
    if (op.timer) clearTimeout(op.timer);
    op.stream?.getTracks().forEach((track) => track.stop());
    op.stream = undefined;
  };
  const cancel = useCallback(() => {
    const op = operation.current;
    operation.current = null;
    if (op) {
      op.controller.abort();
      if (op.recorder) {
        op.recorder.ondataavailable = null;
        op.recorder.onstop = null;
        op.recorder.onerror = null;
        if (op.recorder.state !== "inactive") op.recorder.stop();
      }
      release(op);
    }
    if (mounted.current) setPhase("idle");
  }, []);
  useLayoutEffect(() => {
    mounted.current = true;
    const abort = () => cancel();
    scope.signal.addEventListener("abort", abort);
    return () => {
      mounted.current = false;
      scope.signal.removeEventListener("abort", abort);
      cancel();
    };
  }, [scope, props.conversationId, props.contextKey, props.disabled, cancel]);
  // A context change cancels synchronously at commit; reset its presentation too.
  useEffect(() => {
    setPhase("idle");
  }, [scope, props.conversationId, props.contextKey, props.disabled]);
  const begin = (): Operation | null => {
    if (
      operation.current ||
      !mounted.current ||
      latest.current.disabled ||
      !scope.canUse ||
      !scope.current()
    )
      return null;
    const captured = latest.current;
    const sender = captured.getSender?.() ?? undefined;
    if (captured.getSender && !sender) return null;
    const controller = new AbortController();
    const op: Operation = {
      controller,
      sender,
      current: () =>
        mounted.current &&
        operation.current === op &&
        !controller.signal.aborted &&
        scope.current() &&
        !latest.current.disabled &&
        captured.conversationId === latest.current.conversationId &&
        captured.contextKey === latest.current.contextKey &&
        (!sender ||
          (sender.isConnected &&
            !sender.disabled &&
            !sender.readOnly &&
            latest.current.getSender?.() === sender)),
    };
    operation.current = op;
    return op;
  };
  const submit = async (file: Blob, op: Operation) => {
    if (!op.current()) {
      if (operation.current === op) cancel();
      return;
    }
    setPhase("transcribing");
    try {
      const limit = useUploadLimitStore.getState().uploadMaxSizeMb;
      if (!file.size) throw new TranscriptionError(422, "", "EMPTY_AUDIO");
      if (limit !== null && file.size > limit * 1024 * 1024)
        throw new TranscriptionError(413, "", "FILE_TOO_LARGE");
      const result = await voiceApi.transcribe(
        file,
        scope,
        op.controller.signal,
        props.conversationId ?? undefined,
      );
      if (op.current()) latest.current.onTranscription(result.text, op.sender);
    } catch (error) {
      if (op.current()) message.error(t(transcriptionErrorKey(error)));
    } finally {
      if (operation.current === op) {
        release(op);
        operation.current = null;
        if (mounted.current) setPhase("idle");
      }
    }
  };
  const upload = (file: File) => {
    const op = begin();
    if (op) void submit(file, op);
  };
  const toggleRecording = async () => {
    const existing = operation.current;
    if (existing) {
      if (!existing.current()) {
        cancel();
        return;
      }
      if (existing.recorder?.state === "recording") existing.recorder.stop();
      return;
    }
    const op = begin();
    if (!op) return;
    setPhase("microphone");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!op.current()) {
        stream.getTracks().forEach((track) => track.stop());
        if (operation.current === op) cancel();
        return;
      }
      op.stream = stream;
      const mimeType = ["audio/webm", "audio/mp4", "audio/ogg"].find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      if (!mimeType) throw new Error("Unsupported recorder");
      const recorder = new MediaRecorder(stream, { mimeType });
      op.recorder = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => {
        if (op.current() && e.data.size) chunks.push(e.data);
      };
      recorder.onstop = () => {
        release(op);
        if (op.current())
          void submit(
            new Blob(chunks, { type: recorder.mimeType || mimeType }),
            op,
          );
        else if (operation.current === op) cancel();
      };
      recorder.onerror = () => {
        if (op.current()) message.error(t("chat.speech.microphoneError"));
        cancel();
      };
      recorder.start();
      setPhase("recording");
      op.timer = setTimeout(
        () => {
          if (op.current() && recorder.state === "recording") recorder.stop();
          else if (operation.current === op) cancel();
        },
        5 * 60 * 1000,
      );
    } catch {
      if (op.current()) message.error(t("chat.speech.microphoneError"));
      if (operation.current === op) cancel();
    }
  };
  return {
    phase,
    upload,
    toggleRecording,
    cancel,
    disabled: props.disabled || !scope.canUse,
  };
}
