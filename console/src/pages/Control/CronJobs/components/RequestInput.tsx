import { useEffect, useRef, useState } from "react";
import { Button, Input } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

const wrapText = (text: string) =>
  JSON.stringify(
    [{ content: [{ text, type: "text" }], role: "user" }],
    null,
    2,
  );

// Only unwrap messages that can round-trip without losing other fields.
function readText(value: string): string | null {
  if (!value) return "";
  try {
    const input = JSON.parse(value);
    if (typeof input === "string") return input;
    if (!Array.isArray(input) || input.length !== 1) return null;
    const entry = input[0];
    if (
      entry?.role !== "user" ||
      Object.keys(entry).some((key) => !["role", "content"].includes(key)) ||
      !Array.isArray(entry.content) ||
      entry.content.length !== 1
    )
      return null;
    const block = entry.content[0];
    return block?.type === "text" &&
      typeof block.text === "string" &&
      Object.keys(block).every((key) => ["type", "text"].includes(key))
      ? block.text
      : null;
  } catch {
    return null;
  }
}

interface RequestInputProps {
  value?: string;
  onChange?: (value: string) => void;
  id?: string;
}

export function RequestInput({ value = "", onChange, id }: RequestInputProps) {
  const { t } = useTranslation();
  const [jsonMode, setJsonMode] = useState(() => readText(value) === null);
  const [text, setText] = useState(() => readText(value) ?? "");
  const [jsonDraft, setJsonDraft] = useState(value);
  const lastValue = useRef(value);

  // Form resets, task edits and templates can replace the input externally.
  useEffect(() => {
    if (value === lastValue.current) return;
    lastValue.current = value;
    const plainText = readText(value);
    setText(plainText ?? "");
    setJsonDraft(value);
    setJsonMode(plainText === null);
  }, [value]);

  const emit = (next: string) => {
    lastValue.current = next;
    onChange?.(next);
  };

  const toggleMode = () => {
    if (jsonMode) {
      const plainText = readText(jsonDraft);
      // Keep advanced or unfinished JSON as a draft when returning to text.
      const nextText = plainText ?? text;
      setText(nextText);
      emit(nextText.trim() ? wrapText(nextText) : "");
    } else {
      const nextJson =
        jsonDraft || wrapText(text || t("cronJobs.requestTextExample"));
      setJsonDraft(nextJson);
      emit(nextJson);
    }
    setJsonMode(!jsonMode);
  };

  return (
    <div>
      <Input.TextArea
        id={id}
        rows={6}
        value={jsonMode ? jsonDraft : text}
        placeholder={t("cronJobs.requestTextPlaceholder")}
        style={{
          height: 160,
          minHeight: 160,
          maxHeight: 160,
          resize: "none",
          overflowY: "auto",
          fontSize: 14,
          ...(jsonMode ? { fontFamily: "monospace" } : {}),
        }}
        onChange={(event) => {
          const next = event.target.value;
          if (jsonMode) {
            setJsonDraft(next);
            emit(next);
          } else {
            setText(next);
            const wrapped = next.trim() ? wrapText(next) : "";
            setJsonDraft(wrapped);
            emit(wrapped);
          }
        }}
      />
      <div className={styles.requestInputMode}>
        <Button type="link" size="small" onClick={toggleMode}>
          {t(jsonMode ? "cronJobs.textMode" : "cronJobs.jsonMode")}
        </Button>
      </div>
    </div>
  );
}
