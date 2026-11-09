import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Input, Segmented } from "antd";
import {
  Bold,
  Code,
  Image as ImageIcon,
  Italic,
  Link2,
  List,
  ListChecks,
  ListOrdered,
  Quote,
  Type,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  applyMarkdownAction,
  type MarkdownToolbarAction,
} from "./markdownToolbar";
import { videoMarkdownComponents } from "./PostBody";
import styles from "./index.module.less";

type EditorMode = "edit" | "preview";

export interface MarkdownComposerHandle {
  focus: () => void;
}

export interface MarkdownToolbarItem {
  action: MarkdownToolbarAction;
  label: string;
  icon: ReactNode;
}

/** Shared quick-action definitions so other editors (post composer) can
 *  render the identical markdown toolbar row. */
export function useMarkdownToolbarItems(): MarkdownToolbarItem[] {
  const { t } = useTranslation();
  return useMemo(
    (): MarkdownToolbarItem[] => [
      {
        action: "heading",
        label: t("communityPage.markdownToolbar.heading"),
        icon: <Type size={15} aria-hidden="true" />,
      },
      {
        action: "bold",
        label: t("communityPage.markdownToolbar.bold"),
        icon: <Bold size={15} aria-hidden="true" />,
      },
      {
        action: "italic",
        label: t("communityPage.markdownToolbar.italic"),
        icon: <Italic size={15} aria-hidden="true" />,
      },
      {
        action: "quote",
        label: t("communityPage.markdownToolbar.quote"),
        icon: <Quote size={15} aria-hidden="true" />,
      },
      {
        action: "code",
        label: t("communityPage.markdownToolbar.code"),
        icon: <Code size={15} aria-hidden="true" />,
      },
      {
        action: "link",
        label: t("communityPage.markdownToolbar.link"),
        icon: <Link2 size={15} aria-hidden="true" />,
      },
      {
        action: "ul",
        label: t("communityPage.markdownToolbar.ul"),
        icon: <List size={15} aria-hidden="true" />,
      },
      {
        action: "ol",
        label: t("communityPage.markdownToolbar.ol"),
        icon: <ListOrdered size={15} aria-hidden="true" />,
      },
      {
        action: "task",
        label: t("communityPage.markdownToolbar.task"),
        icon: <ListChecks size={15} aria-hidden="true" />,
      },
      {
        action: "image",
        label: t("communityPage.markdownToolbar.image"),
        icon: <ImageIcon size={15} aria-hidden="true" />,
      },
    ],
    [t],
  );
}

interface MarkdownComposerProps {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  maxLength?: number;
  disabled?: boolean;
  ariaLabel?: string;
}

/**
 * Markdown composer mirroring the platform MarkdownTextArea: a quick-action
 * icon row (heading/bold/italic/quote/code/link/lists/task/image) above the
 * input plus an edit/preview switch; preview renders the draft as Markdown.
 */
export const MarkdownComposer = forwardRef<
  MarkdownComposerHandle,
  MarkdownComposerProps
>(function MarkdownComposer(
  { value, onChange, placeholder, maxLength, disabled, ariaLabel },
  ref,
) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<EditorMode>("edit");
  const editor = useRef<HTMLTextAreaElement | null>(null);
  const items = useMarkdownToolbarItems();

  // antd exposes the native textarea through the ref's resizableTextArea.
  const bindEditor = (
    node: { resizableTextArea?: { textArea?: HTMLTextAreaElement } } | null,
  ) => {
    editor.current = node?.resizableTextArea?.textArea ?? null;
  };

  // Clicking anywhere in the body (including preview) activates the editor.
  const focusEditor = useCallback(() => {
    setMode("edit");
    requestAnimationFrame(() => editor.current?.focus());
  }, []);

  useImperativeHandle(ref, () => ({
    focus: focusEditor,
  }));

  const apply = (action: MarkdownToolbarAction) => {
    const el = editor.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    const { nextValue, selectionStart, selectionEnd } = applyMarkdownAction(
      value,
      start,
      end,
      action,
    );
    if (maxLength != null && nextValue.length > maxLength) return;
    onChange(nextValue);
    requestAnimationFrame(() => {
      const textarea = editor.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(selectionStart, selectionEnd);
    });
  };

  return (
    <div className={styles.markdownComposer}>
      <div className={styles.composerToolbar}>
        <div className={styles.toolbarGroup}>
          {items.map((item) => (
            <button
              key={item.action}
              type="button"
              title={item.label}
              aria-label={item.label}
              tabIndex={mode === "edit" ? 0 : -1}
              disabled={disabled || mode === "preview"}
              className={styles.toolbarBtn}
              // Keep the textarea selection alive while clicking the toolbar.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => apply(item.action)}
            >
              {item.icon}
            </button>
          ))}
        </div>
        <Segmented
          size="small"
          value={mode}
          onChange={(next) => setMode(next as EditorMode)}
          disabled={disabled}
          options={[
            { label: t("common.edit"), value: "edit" },
            { label: t("common.preview"), value: "preview" },
          ]}
        />
      </div>
      <div className={styles.composerBody} onClick={focusEditor}>
        {mode === "edit" ? (
          <Input.TextArea
            ref={bindEditor}
            aria-label={ariaLabel}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            className={styles.composerInput}
            maxLength={maxLength}
            placeholder={placeholder}
            disabled={disabled}
            variant="borderless"
          />
        ) : (
          <div className={`${styles.body} ${styles.composerPreview}`}>
            {value.trim() ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={videoMarkdownComponents}
              >
                {value}
              </ReactMarkdown>
            ) : (
              <p className={styles.previewEmpty}>
                {t("communityPage.markdownPreviewEmpty")}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
});

export default MarkdownComposer;
