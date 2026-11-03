import { Button, Input, Modal } from "antd";
import type { SenderInputProps } from "@agentscope-ai/chat/lib/Sender";
import { ClipboardPaste, Paperclip, X } from "lucide-react";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ComponentRef,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { setTextareaValue } from "./utils";
import styles from "./LongTextPaste.module.less";

type PasteChoice = "text" | "file" | "cancel" | undefined;
type PasteRequest = {
  text: string;
  resolve: (choice: PasteChoice) => void;
};
type TextAreaProps = Omit<SenderInputProps, "ref">;

const LongTextPasteContext = createContext<
  ((text: string) => Promise<PasteChoice>) | undefined
>(undefined);

export function LongTextPasteProvider({
  children,
  enabled,
  scopeKey,
}: {
  children: ReactNode;
  enabled: boolean;
  scopeKey?: string;
}) {
  const { t } = useTranslation();
  const [request, setRequest] = useState<PasteRequest>();
  const requestRef = useRef<PasteRequest>();
  const choosePaste = useCallback(
    (text: string) =>
      new Promise<PasteChoice>((resolve) => {
        requestRef.current?.resolve(undefined);
        const next = { text, resolve };
        requestRef.current = next;
        setRequest(next);
      }),
    [],
  );

  const finish = (choice: PasteChoice) => {
    requestRef.current?.resolve(choice);
    requestRef.current = undefined;
    setRequest(undefined);
  };

  useEffect(() => {
    setRequest(undefined);
    return () => {
      requestRef.current?.resolve(undefined);
      requestRef.current = undefined;
    };
  }, [enabled, scopeKey]);

  return (
    <LongTextPasteContext.Provider value={enabled ? choosePaste : undefined}>
      {children}
      <Modal
        open={!!request}
        title={t("chat.longTextPaste.title")}
        onCancel={() => finish("cancel")}
        focusTriggerAfterClose={false}
        destroyOnHidden
        closeIcon={<X size={16} />}
        width={480}
        footer={
          <div className={styles.pasteActions}>
            <Button onClick={() => finish("cancel")}>
              {t("common.cancel")}
            </Button>
            <Button
              icon={<Paperclip size={16} />}
              onClick={() => finish("file")}
            >
              {t("chat.longTextPaste.asFile")}
            </Button>
            <Button
              type="primary"
              icon={<ClipboardPaste size={16} />}
              onClick={() => finish("text")}
              autoFocus
            >
              {t("chat.longTextPaste.asText")}
            </Button>
          </div>
        }
      >
        {t("chat.longTextPaste.characters", {
          count: request?.text.length ?? 0,
        })}
      </Modal>
    </LongTextPasteContext.Provider>
  );
}

export const LongTextPasteInput = forwardRef<
  ComponentRef<typeof Input.TextArea>,
  TextAreaProps
>(function LongTextPasteInput(
  { onPaste, onSelect, onSelectionChange, ...props },
  ref,
) {
  const choosePaste = useContext(LongTextPasteContext);

  return (
    <Input.TextArea
      {...props}
      ref={ref}
      onSelect={(event) => {
        if (onSelect) onSelect(event);
        else {
          const { selectionStart, selectionEnd } = event.currentTarget;
          onSelectionChange?.(selectionStart, selectionEnd);
        }
      }}
      onPaste={(event) => {
        const clipboard = event.clipboardData;
        const text = clipboard?.getData("text/plain") ?? "";
        if (
          !choosePaste ||
          !onPaste ||
          props.disabled ||
          props.readOnly ||
          text.length <= 10_000 ||
          clipboard?.files.length ||
          Array.from(clipboard?.items ?? []).some(
            (item) => item.kind === "file",
          )
        ) {
          onPaste?.(event);
          return;
        }
        event.preventDefault();
        const textarea = event.currentTarget;
        const draft = textarea.value;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        void choosePaste(text).then((choice) => {
          if (
            !choice ||
            !textarea.isConnected ||
            textarea.disabled ||
            textarea.readOnly
          )
            return;
          if (choice === "file") {
            const clipboardData = new DataTransfer();
            clipboardData.items.add(
              new File([text], `prompt-${Date.now()}.txt`, {
                type: "text/plain;charset=utf-8",
              }),
            );
            // Reuse the sender's file-paste path and attachment error state.
            const filePaste = new ClipboardEvent("paste", {
              clipboardData,
              cancelable: true,
            });
            onPaste(
              filePaste as unknown as Parameters<
                NonNullable<TextAreaProps["onPaste"]>
              >[0],
            );
          }
          // A pending send may clear the draft while the dialog is open.
          const current = textarea.value;
          const insertStart = current === draft ? start : current.length;
          const insertEnd = current === draft ? end : current.length;
          textarea.focus();
          textarea.setSelectionRange(insertStart, insertEnd);
          if (choice === "text") {
            // Native insertion preserves undo history, unlike assigning value.
            const inserted = textarea.ownerDocument.execCommand?.(
              "insertText",
              false,
              text,
            );
            if (!inserted) {
              setTextareaValue(
                textarea,
                `${current.slice(0, insertStart)}${text}${current.slice(
                  insertEnd,
                )}`,
              );
              const cursor = insertStart + text.length;
              textarea.setSelectionRange(cursor, cursor);
            }
          }
        });
      }}
    />
  );
});
