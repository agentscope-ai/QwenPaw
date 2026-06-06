import React, { useCallback, useState } from "react";
import { Attachments, Sender } from "@agentscope-ai/chat";
import { Upload } from "antd";
import type { UploadFile, UploadProps } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { SparkAttachmentLine } from "@agentscope-ai/icons";
import { useChatContext } from "../context/ChatContext";
import { useChatStore } from "../stores/chatStore";
import {
  useIMEComposition,
  useMessageHistory,
  useCommandSuggestions,
} from "../hooks/useChatInput";
import { useChatInputDraft } from "../hooks/useChatInputDraft";
import { useChatMessages } from "../hooks/useChatMessages";
import CommandSuggestions from "./CommandSuggestions";
import type { CommandSuggestion, ChatInputData } from "../types";
import styles from "./MessageInput.module.less";

export interface MessageInputProps {
  /** Placeholder text */
  placeholder?: string;
  /** Slash commands */
  commands?: CommandSuggestion[];
  /** Enable file attachments */
  enableAttachments?: boolean;
  /** Custom prefix UI in the action bar */
  prefix?: React.ReactNode;
  /** Custom suffix UI in the action bar */
  suffix?: React.ReactNode;
  /** Maximum file size in MB */
  maxFileSize?: number;
  /** Upload handler */
  onUpload?: (file: File) => Promise<{ url: string }>;
  /** Whether multimodal is supported */
  supportsMultimodal?: boolean;
  /** Whether to allow built-in speech (when custom whisper is not available) */
  allowSpeech?: boolean;
}

const MessageInput: React.FC<MessageInputProps> = ({
  placeholder = "Type a message...",
  commands = [],
  enableAttachments = true,
  prefix,
  suffix,
  maxFileSize = 10,
  onUpload,
  supportsMultimodal: _supportsMultimodal = false,
  allowSpeech = false,
}) => {
  void _supportsMultimodal;
  const { onSend, onCancel } = useChatContext();
  const isGenerating = useChatStore((s) => s.isGenerating);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const [value, setValue] = useState("");
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const isComposingRef = useIMEComposition();

  const { getUserMessageTexts } = useChatMessages({
    sessionId: activeSessionId,
  });

  // Draft persistence – save unsent input to localStorage per session
  const { clearDraft } = useChatInputDraft({
    sessionId: activeSessionId,
    value,
    setValue,
  });

  // History navigation
  useMessageHistory({ getUserMessages: getUserMessageTexts });

  // Command suggestions
  const {
    suggestions: commandSuggestions,
    visible: showCommands,
    activeIndex: commandActiveIndex,
    handleInputChange: handleCommandInput,
    selectCommand,
    handleKeyDown: handleCommandKeyDown,
    dismiss: dismissCommands,
  } = useCommandSuggestions({ commands });

  const handleChange = useCallback(
    (val: string) => {
      setValue(val);
      handleCommandInput(val);
    },
    [handleCommandInput],
  );

  const handleSubmit = useCallback(() => {
    if (isComposingRef.current) return;
    if (!value.trim() && fileList.length === 0) return;

    const input: ChatInputData = {
      text: value.trim(),
      files: fileList,
    };

    onSend(input);
    setValue("");
    setFileList([]);
    dismissCommands();
    clearDraft();
  }, [value, fileList, onSend, isComposingRef, dismissCommands, clearDraft]);

  const handleCancel = useCallback(() => {
    onCancel();
  }, [onCancel]);

  const handleCommandSelect = useCallback(
    (cmd: CommandSuggestion) => {
      const selected = selectCommand(cmd);
      setValue(selected);
    },
    [selectCommand],
  );

  const handleFileUpload: UploadProps["customRequest"] = useCallback(
    async (options: any) => {
      const { file, onSuccess, onError } = options;
      const sizeMb = (file as File).size / 1024 / 1024;
      if (sizeMb > maxFileSize) {
        onError?.(new Error(`File exceeds ${maxFileSize}MB limit`));
        return;
      }

      if (onUpload) {
        try {
          const res = await onUpload(file as File);
          onSuccess?.({ url: res.url });
        } catch (e) {
          onError?.(e instanceof Error ? e : new Error(String(e)));
        }
      }
    },
    [maxFileSize, onUpload],
  );

  // Max text length before converting to file
  const TEXT_FILE_THRESHOLD = 2000;

  // Handle paste: images from clipboard → upload as file; long text → .txt file
  const handlePaste = useCallback(
    async (e: React.ClipboardEvent) => {
      if (!onUpload) return;

      const items = e.clipboardData?.items;
      if (!items) return;

      // Check for image in clipboard
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.type.startsWith("image/")) {
          e.preventDefault();
          const blob = item.getAsFile();
          if (!blob) continue;
          const ext = item.type.split("/")[1] || "png";
          const file = new File([blob], `clipboard_${Date.now()}.${ext}`, {
            type: item.type,
          });
          try {
            const res = await onUpload(file);
            const newFile: UploadFile = {
              uid: `paste-${Date.now()}-${i}`,
              name: file.name,
              status: "done",
              type: file.type,
              size: file.size,
              url: res.url,
              response: { url: res.url },
            };
            setFileList((prev) => [...prev, newFile]);
          } catch {
            // silently ignore upload failure
          }
          return;
        }
      }

      // Check for long text → convert to .txt file
      const text = e.clipboardData?.getData("text/plain");
      if (text && text.length > TEXT_FILE_THRESHOLD) {
        e.preventDefault();
        const blob = new Blob([text], { type: "text/plain" });
        const file = new File([blob], `pasted_text_${Date.now()}.txt`, {
          type: "text/plain",
        });
        try {
          const res = await onUpload(file);
          const newFile: UploadFile = {
            uid: `paste-txt-${Date.now()}`,
            name: file.name,
            status: "done",
            type: file.type,
            size: file.size,
            url: res.url,
            response: { url: res.url },
          };
          setFileList((prev) => [...prev, newFile]);
        } catch {
          // fallback: just paste as text
          setValue((prev) => prev + text);
        }
        return;
      }
    },
    [onUpload],
  );

  // Sender prefix: attachment button + custom prefix (e.g. whisper)
  const senderPrefix = (
    <>
      {enableAttachments && onUpload && (
        <Upload
          fileList={fileList}
          showUploadList={false}
          customRequest={handleFileUpload}
          onChange={(info) => setFileList(info.fileList)}
          multiple
        >
          <IconButton icon={<SparkAttachmentLine />} bordered={false} />
        </Upload>
      )}
      {prefix}
    </>
  );

  // File preview header: Attachments inside Sender.Header (Spark Design pattern)
  const headerNode =
    enableAttachments && onUpload ? (
      <Sender.Header closable={false} open={fileList.length > 0}>
        <Attachments
          items={fileList}
          onChange={(info) => setFileList(info.fileList)}
        />
      </Sender.Header>
    ) : undefined;

  return (
    <div className={styles.inputContainer}>
      {showCommands && commandSuggestions.length > 0 && (
        <CommandSuggestions
          suggestions={commandSuggestions}
          activeIndex={commandActiveIndex}
          onSelect={handleCommandSelect}
          onDismiss={dismissCommands}
        />
      )}
      <div className={styles.inputWrapper}>
        {prefix && <div className={styles.prefixArea}>{prefix}</div>}
        <div
          className={styles.senderArea}
          onPaste={handlePaste}
          onKeyDown={(e) => {
            const selected = handleCommandKeyDown(
              e as unknown as React.KeyboardEvent,
            );
            if (selected) {
              const selectedValue = selectCommand(selected);
              setValue(selectedValue);
            }
          }}
        >
          <Sender
            value={value}
            onChange={handleChange}
            onSubmit={handleSubmit}
            onCancel={handleCancel}
            loading={isGenerating}
            placeholder={placeholder}
            allowSpeech={allowSpeech}
            submitType="enter"
            prefix={senderPrefix}
            header={headerNode}
          />
        </div>
        {suffix && <div className={styles.suffixArea}>{suffix}</div>}
      </div>
    </div>
  );
};

export default MessageInput;
