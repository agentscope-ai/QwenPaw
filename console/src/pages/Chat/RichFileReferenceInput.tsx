import {
  $applyNodeReplacement,
  $createLineBreakNode,
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $getSelection,
  $isElementNode,
  $isRangeSelection,
  $isTextNode,
  COMMAND_PRIORITY_HIGH,
  DecoratorNode,
  KEY_ENTER_COMMAND,
  PASTE_COMMAND,
  type EditorConfig,
  type LexicalEditor,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
} from "lexical";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { PlainTextPlugin } from "@lexical/react/LexicalPlainTextPlugin";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { Input, Popover, theme } from "antd";
import { Code2, FileText, type LucideIcon } from "lucide-react";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  type CompositionEvent,
  type ComponentProps,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { getLastEditorCopy } from "../Coding/lastEditorCopy";
import {
  compactFileReferenceLabel,
  splitRichComposerValue,
  type ParsedFileReference,
} from "./fileReferenceFormatting";
import { setTextareaValue } from "./utils";
import styles from "./RichFileReferenceInput.module.less";

type TextAreaProps = ComponentProps<typeof Input.TextArea>;

type OpenReference = (
  reference: ParsedFileReference,
  trigger: HTMLElement,
) => void;

const OpenReferenceContext = createContext<OpenReference | undefined>(
  undefined,
);

export function RichFileReferenceInputProvider({
  children,
  onOpenReference,
}: {
  children: ReactNode;
  onOpenReference: OpenReference;
}) {
  return (
    <OpenReferenceContext.Provider value={onOpenReference}>
      {children}
    </OpenReferenceContext.Provider>
  );
}

interface SerializedFileReferenceNode extends SerializedLexicalNode {
  raw: string;
  reference: ParsedFileReference;
}

class FileReferenceNode extends DecoratorNode<ReactNode> {
  __raw: string;
  __reference: ParsedFileReference;

  static getType() {
    return "file-reference";
  }

  static clone(node: FileReferenceNode) {
    return new FileReferenceNode(node.__raw, node.__reference, node.__key);
  }

  static importJSON(
    serialized: SerializedLexicalNode & Record<string, unknown>,
  ) {
    const value = serialized as unknown as SerializedFileReferenceNode;
    return $createFileReferenceNode(value.raw, value.reference);
  }

  constructor(raw: string, reference: ParsedFileReference, key?: NodeKey) {
    super(key);
    this.__raw = raw;
    this.__reference = reference;
  }

  exportJSON(): SerializedFileReferenceNode {
    return {
      ...super.exportJSON(),
      type: "file-reference",
      version: 1,
      raw: this.__raw,
      reference: this.__reference,
    };
  }

  createDOM(_config: EditorConfig) {
    const element = document.createElement("span");
    element.className = styles.atomicNode;
    return element;
  }

  updateDOM() {
    return false;
  }

  isInline() {
    return true;
  }

  getTextContent() {
    return this.__raw;
  }

  decorate() {
    return <FileReferenceChip reference={this.__reference} />;
  }
}

function $createFileReferenceNode(raw: string, reference: ParsedFileReference) {
  return $applyNodeReplacement(new FileReferenceNode(raw, reference));
}

interface SerializedCodeSnippetNode extends SerializedLexicalNode {
  raw: string;
  language: string;
  code: string;
}

class CodeSnippetNode extends DecoratorNode<ReactNode> {
  __raw: string;
  __language: string;
  __code: string;

  static getType() {
    return "code-snippet";
  }

  static clone(node: CodeSnippetNode) {
    return new CodeSnippetNode(
      node.__raw,
      node.__language,
      node.__code,
      node.__key,
    );
  }

  static importJSON(
    serialized: SerializedLexicalNode & Record<string, unknown>,
  ) {
    const value = serialized as unknown as SerializedCodeSnippetNode;
    return $createCodeSnippetNode(value.raw, value.language, value.code);
  }

  constructor(raw: string, language: string, code: string, key?: NodeKey) {
    super(key);
    this.__raw = raw;
    this.__language = language;
    this.__code = code;
  }

  exportJSON(): SerializedCodeSnippetNode {
    return {
      ...super.exportJSON(),
      type: "code-snippet",
      version: 1,
      raw: this.__raw,
      language: this.__language,
      code: this.__code,
    };
  }

  createDOM(_config: EditorConfig) {
    const element = document.createElement("span");
    element.className = styles.atomicNode;
    return element;
  }

  updateDOM() {
    return false;
  }

  isInline() {
    return true;
  }

  getTextContent() {
    return this.__raw;
  }

  decorate() {
    return <CodeSnippetChip language={this.__language} code={this.__code} />;
  }
}

function $createCodeSnippetNode(raw: string, language: string, code: string) {
  return $applyNodeReplacement(new CodeSnippetNode(raw, language, code));
}

function AtomicChip({
  icon: Icon,
  label,
  title,
  onClick,
  className = "",
}: {
  icon: LucideIcon;
  label: string;
  title?: string;
  onClick?: (trigger: HTMLButtonElement) => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={`${styles.atomicChip} ${className}`}
      contentEditable={false}
      title={title}
      tabIndex={-1}
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => onClick?.(event.currentTarget)}
    >
      <Icon size={14} aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}

function FileReferenceChip({ reference }: { reference: ParsedFileReference }) {
  const openReference = useContext(OpenReferenceContext);
  return (
    <AtomicChip
      icon={FileText}
      label={compactFileReferenceLabel(reference)}
      title={reference.path}
      onClick={(trigger) => openReference?.(reference, trigger)}
    />
  );
}

function CodeSnippetChip({
  language,
  code,
}: {
  language: string;
  code: string;
}) {
  const { t } = useTranslation();
  const lineCount = code ? code.split(/\r?\n/).length : 0;
  return (
    <Popover
      trigger="click"
      placement="topLeft"
      overlayClassName={styles.codePopover}
      content={
        <div className={styles.codePreview}>
          <div className={styles.codePreviewHeader}>{language}</div>
          <pre>
            <code>{code}</code>
          </pre>
        </div>
      }
    >
      <span className={styles.codeChipHost} contentEditable={false}>
        <AtomicChip
          icon={Code2}
          label={t("chat.fileReference.codeSnippet", {
            count: lineCount,
          })}
          className={styles.codeChip}
        />
      </span>
    </Popover>
  );
}

function appendTextWithLineBreaks(
  parent: ReturnType<typeof $createParagraphNode>,
  value: string,
) {
  const lines = value.split(/\r?\n/);
  lines.forEach((line, index) => {
    if (index > 0) parent.append($createLineBreakNode());
    if (line) parent.append($createTextNode(line));
  });
}

function replaceEditorValue(value: string) {
  const root = $getRoot();
  root.clear();
  const paragraph = $createParagraphNode();
  root.append(paragraph);
  for (const segment of splitRichComposerValue(value)) {
    if (segment.kind === "file") {
      paragraph.append(
        $createFileReferenceNode(segment.raw, segment.reference),
      );
    } else if (segment.kind === "code") {
      paragraph.append(
        $createCodeSnippetNode(segment.raw, segment.language, segment.code),
      );
    } else {
      appendTextWithLineBreaks(paragraph, segment.raw);
    }
  }
}

function selectRawOffset(rawOffset: number) {
  const paragraph = $getRoot().getFirstChild();
  if (!$isElementNode(paragraph)) return;
  const children = paragraph.getChildren();
  let offset = 0;

  for (let index = 0; index < children.length; index += 1) {
    const child = children[index];
    const size = nodeRawSize(child);
    if ($isTextNode(child) && rawOffset <= offset + size) {
      const textOffset = Math.max(0, rawOffset - offset);
      child.select(textOffset, textOffset);
      return;
    }
    if (!$isTextNode(child) && rawOffset <= offset + size) {
      const elementOffset = rawOffset <= offset ? index : index + 1;
      paragraph.select(elementOffset, elementOffset);
      return;
    }
    offset += size;
  }

  paragraph.selectEnd();
}

function nodeRawSize(node: LexicalNode) {
  return node.getTextContent().length;
}

function selectionPointOffset(targetKey: string, targetOffset: number): number {
  let rawOffset = 0;
  let resolved: number | null = null;

  const visit = (node: LexicalNode) => {
    if (resolved !== null) return;
    if (node.getKey() === targetKey) {
      if ($isTextNode(node)) {
        resolved =
          rawOffset + Math.min(targetOffset, node.getTextContentSize());
        return;
      }
      if ($isElementNode(node)) {
        const children = node.getChildren();
        resolved =
          rawOffset +
          children
            .slice(0, targetOffset)
            .reduce((sum, child) => sum + nodeRawSize(child), 0);
        return;
      }
      resolved = rawOffset;
      return;
    }
    if ($isElementNode(node)) {
      for (const child of node.getChildren()) {
        visit(child);
        if (resolved !== null) return;
        rawOffset += nodeRawSize(child);
      }
    }
  };

  visit($getRoot());
  return resolved ?? rawOffset;
}

function RichEditorBridge({
  value,
  editable,
  hiddenTextarea,
  editorRef,
  onRawChange,
}: {
  value: string;
  editable: boolean;
  hiddenTextarea: React.RefObject<HTMLTextAreaElement | null>;
  editorRef: React.MutableRefObject<LexicalEditor | null>;
  onRawChange: (value: string, start: number, end: number) => void;
}) {
  const [editor] = useLexicalComposerContext();
  const valueRef = useRef(value);
  valueRef.current = value;
  editorRef.current = editor;

  useEffect(() => {
    editor.setEditable(editable);
  }, [editable, editor]);

  useLayoutEffect(() => {
    const current = editor
      .getEditorState()
      .read(() => $getRoot().getTextContent());
    if (current === value) return;
    editor.update(() => {
      replaceEditorValue(value);
      selectRawOffset(hiddenTextarea.current?.selectionStart ?? value.length);
    });
  }, [editor, hiddenTextarea, value]);

  useEffect(
    () => () => {
      if (editorRef.current === editor) editorRef.current = null;
    },
    [editor, editorRef],
  );

  return (
    <OnChangePlugin
      ignoreSelectionChange={false}
      onChange={(editorState) => {
        editorState.read(() => {
          const raw = $getRoot().getTextContent();
          const selection = $getSelection();
          let start = raw.length;
          let end = raw.length;
          if ($isRangeSelection(selection)) {
            start = selectionPointOffset(
              selection.anchor.key,
              selection.anchor.offset,
            );
            end = selectionPointOffset(
              selection.focus.key,
              selection.focus.offset,
            );
            if (start > end) [start, end] = [end, start];
          }
          if (raw !== valueRef.current) {
            onRawChange(raw, start, end);
          } else if (hiddenTextarea.current) {
            hiddenTextarea.current.selectionStart = start;
            hiddenTextarea.current.selectionEnd = end;
          }
        });
      }}
    />
  );
}

function KeyCommandPlugin({
  onKeyDown,
  onPressEnter,
}: {
  onKeyDown?: TextAreaProps["onKeyDown"];
  onPressEnter?: TextAreaProps["onPressEnter"];
}) {
  const [editor] = useLexicalComposerContext();

  useEffect(
    () =>
      editor.registerCommand(
        KEY_ENTER_COMMAND,
        (event) => {
          if (!event) return false;
          const reactLikeEvent =
            event as unknown as KeyboardEvent<HTMLTextAreaElement>;
          onKeyDown?.(reactLikeEvent);
          if (event.defaultPrevented) return true;
          onPressEnter?.(reactLikeEvent);
          return event.defaultPrevented;
        },
        COMMAND_PRIORITY_HIGH,
      ),
    [editor, onKeyDown, onPressEnter],
  );

  return null;
}

function insertRichValueAtSelection(value: string) {
  const selection = $getSelection();
  if (!$isRangeSelection(selection)) return;

  const nodes: LexicalNode[] = [];
  for (const segment of splitRichComposerValue(value)) {
    if (segment.kind === "file") {
      nodes.push($createFileReferenceNode(segment.raw, segment.reference));
    } else if (segment.kind === "code") {
      nodes.push(
        $createCodeSnippetNode(segment.raw, segment.language, segment.code),
      );
    } else {
      const lines = segment.raw.split(/\r?\n/);
      lines.forEach((line, index) => {
        if (index > 0) nodes.push($createLineBreakNode());
        if (line) nodes.push($createTextNode(line));
      });
    }
  }
  selection.insertNodes(nodes);
}

function EditorPastePlugin({
  onPaste,
}: {
  onPaste?: TextAreaProps["onPaste"];
}) {
  const [editor] = useLexicalComposerContext();

  useEffect(
    () =>
      editor.registerCommand(
        PASTE_COMMAND,
        (event) => {
          onPaste?.(
            event as unknown as Parameters<
              NonNullable<TextAreaProps["onPaste"]>
            >[0],
          );
          if (event.defaultPrevented) return true;

          const lastCopy = getLastEditorCopy();
          const pasted =
            "clipboardData" in event
              ? event.clipboardData?.getData("text/plain")
              : undefined;
          if (
            !lastCopy ||
            Date.now() - lastCopy.ts > 60_000 ||
            pasted !== lastCopy.text
          ) {
            return false;
          }

          event.preventDefault();
          editor.update(() => insertRichValueAtSelection(lastCopy.formatted));
          return true;
        },
        COMMAND_PRIORITY_HIGH,
      ),
    [editor, onPaste],
  );

  return null;
}

function EditableSurface({
  onKeyDown,
  onFocus,
  onBlur,
  onCompositionStart,
  onCompositionEnd,
}: {
  onKeyDown?: TextAreaProps["onKeyDown"];
  onFocus?: TextAreaProps["onFocus"];
  onBlur?: TextAreaProps["onBlur"];
  onCompositionStart?: TextAreaProps["onCompositionStart"];
  onCompositionEnd?: TextAreaProps["onCompositionEnd"];
}) {
  return (
    <ContentEditable
      className={styles.richEditor}
      role="textbox"
      aria-multiline="true"
      spellCheck={false}
      onKeyDown={(event) => {
        if (event.key !== "Enter") {
          onKeyDown?.(event as unknown as KeyboardEvent<HTMLTextAreaElement>);
        }
      }}
      onFocus={(event) =>
        onFocus?.(event as unknown as FocusEvent<HTMLTextAreaElement>)
      }
      onBlur={(event) =>
        onBlur?.(event as unknown as FocusEvent<HTMLTextAreaElement>)
      }
      onCompositionStart={(event) =>
        onCompositionStart?.(
          event as unknown as CompositionEvent<HTMLTextAreaElement>,
        )
      }
      onCompositionEnd={(event) =>
        onCompositionEnd?.(
          event as unknown as CompositionEvent<HTMLTextAreaElement>,
        )
      }
    />
  );
}

const RichFileReferenceInput = forwardRef<unknown, TextAreaProps>(
  function RichFileReferenceInput(
    {
      value,
      placeholder,
      disabled,
      readOnly,
      className,
      style,
      onChange,
      onFocus,
      onBlur,
      onKeyDown,
      onPressEnter,
      onPaste,
      onCompositionStart,
      onCompositionEnd,
      autoSize: _autoSize,
      variant: _variant,
      ...textareaProps
    },
    ref,
  ) {
    const { token } = theme.useToken();
    const rawValue = String(value ?? "");
    const hiddenTextarea = useRef<HTMLTextAreaElement>(null);
    const editorRef = useRef<LexicalEditor | null>(null);

    useImperativeHandle(
      ref,
      () => ({
        focus: () => editorRef.current?.focus(),
        blur: () => editorRef.current?.blur(),
        resizableTextArea: { textArea: hiddenTextarea.current },
      }),
      [],
    );

    const handleRawChange = useCallback(
      (nextValue: string, start: number, end: number) => {
        const textarea = hiddenTextarea.current;
        if (!textarea) return;
        setTextareaValue(textarea, nextValue);
        textarea.selectionStart = start;
        textarea.selectionEnd = end;
      },
      [],
    );

    return (
      <div
        className={`${styles.richInputRoot} ${className ?? ""}`}
        style={style}
        data-disabled={disabled || undefined}
      >
        <LexicalComposer
          initialConfig={{
            namespace: "QwenPawRichFileReferenceInput",
            editable: !disabled && !readOnly,
            nodes: [FileReferenceNode, CodeSnippetNode],
            onError(error) {
              throw error;
            },
            theme: {
              paragraph: styles.paragraph,
              text: {
                base: styles.text,
              },
            },
          }}
        >
          <PlainTextPlugin
            contentEditable={
              <EditableSurface
                onKeyDown={onKeyDown}
                onFocus={onFocus}
                onBlur={onBlur}
                onCompositionStart={onCompositionStart}
                onCompositionEnd={onCompositionEnd}
              />
            }
            placeholder={
              <div
                className={styles.placeholder}
                style={{ color: token.colorTextPlaceholder }}
              >
                {placeholder}
              </div>
            }
            ErrorBoundary={LexicalErrorBoundary}
          />
          <HistoryPlugin />
          <RichEditorBridge
            value={rawValue}
            editable={!disabled && !readOnly}
            hiddenTextarea={hiddenTextarea}
            editorRef={editorRef}
            onRawChange={handleRawChange}
          />
          <EditorPastePlugin onPaste={onPaste} />
          <KeyCommandPlugin onKeyDown={onKeyDown} onPressEnter={onPressEnter} />
        </LexicalComposer>
        <textarea
          {...textareaProps}
          ref={hiddenTextarea}
          className={styles.hiddenTextarea}
          value={rawValue}
          readOnly={readOnly}
          disabled={disabled}
          tabIndex={-1}
          aria-hidden="true"
          spellCheck={false}
          onChange={onChange}
          onFocus={() => {
            const editor = editorRef.current;
            if (!editor) return;
            const offset =
              hiddenTextarea.current?.selectionStart ?? rawValue.length;
            editor.focus();
            editor.update(() => selectRawOffset(offset));
          }}
        />
      </div>
    );
  },
);

export default RichFileReferenceInput;
