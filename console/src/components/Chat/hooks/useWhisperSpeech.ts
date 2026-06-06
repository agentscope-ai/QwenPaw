import { useCallback, useEffect, useRef, useState } from "react";
import { agentApi } from "../../../api/modules/agent";

export function useWhisperSpeech<T = unknown>() {
  const whisperSpeechRef = useRef<T>(null);
  const [whisperEnabled, setWhisperEnabled] = useState(false);

  useEffect(() => {
    agentApi
      .getTranscriptionProviderType()
      .then((res) =>
        setWhisperEnabled(res.transcription_provider_type !== "disabled"),
      )
      .catch(() => setWhisperEnabled(false));
  }, []);

  const handleTranscription = useCallback((text: string) => {
    const textarea = document.querySelector(
      '[class*="senderArea"] textarea',
    ) as HTMLTextAreaElement | null;
    if (!textarea) return;

    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    const newValue = textarea.value ? `${textarea.value} ${text}` : text;
    nativeInputValueSetter?.call(textarea, newValue);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
  }, []);

  return { whisperEnabled, whisperSpeechRef, handleTranscription };
}
