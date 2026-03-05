import { Card, Radio, Input, Button, Space, Typography } from "antd";
import XMarkdown from "@ant-design/x-markdown";
import { createStyles } from "antd-style";
import { useMemo, useState, useCallback } from "react";
import { CheckCircleFilled } from "@ant-design/icons";
import { getApiUrl, getApiToken } from "../../../api/config";

interface OptionItem {
  type: "fixed" | "editable";
  label: string;
}

interface CardData {
  text: string;
  options: OptionItem[];
}

interface CustomWindow extends Window {
  currentSessionId?: string;
}

declare const window: CustomWindow;

const useStyles = createStyles(({ css, token }) => ({
  container: css`
    width: 100%;
    border-radius: 12px;
    border: 1px solid ${token.colorBorderSecondary};
    overflow: hidden;

    .ant-card-body {
      padding: 20px 24px;
    }
  `,
  markdownSection: css`
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid ${token.colorBorderSecondary};

    & > *:last-child {
      margin-bottom: 0;
    }
  `,
  optionsSection: css`
    margin-bottom: 20px;
  `,
  optionsLabel: css`
    display: block;
    margin-bottom: 10px;
    font-weight: 500;
    color: ${token.colorTextSecondary};
  `,
  editableInput: css`
    margin-top: 12px;
  `,
  confirmBtn: css`
    margin-top: 4px;
  `,
  confirmedBanner: css`
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: ${token.colorSuccessBg};
    border-radius: 8px;
    margin-top: 4px;
  `,
  confirmedPrefix: css`
    color: ${token.colorTextSecondary};
    margin-right: 6px;
  `,
  confirmedValue: css`
    font-weight: 600;
    color: ${token.colorText};
  `,
}));

function parseCardArgs(content: any[]): CardData | null {
  try {
    const argsRaw = content[0]?.data?.arguments;
    if (!argsRaw) return null;
    const args = typeof argsRaw === "string" ? JSON.parse(argsRaw) : argsRaw;
    const opts =
      typeof args.options === "string"
        ? JSON.parse(args.options)
        : args.options;
    if (args.text && Array.isArray(opts)) {
      return { text: args.text, options: opts };
    }
  } catch {
    /* fall through */
  }
  return null;
}

interface CompletedDisplay {
  prefix: string;
  value: string;
}

function formatCompletedDisplay(raw: string): CompletedDisplay {
  const fixedMatch = raw.match(/^用户选择的是(.+)$/);
  if (fixedMatch && !raw.includes("补充内容为")) {
    return { prefix: "你的选择是", value: fixedMatch[1] };
  }
  const editableMatch = raw.match(/补充内容为(.+)$/);
  if (editableMatch) {
    return { prefix: "你的输入是", value: editableMatch[1] };
  }
  return { prefix: "", value: raw };
}

function extractPlainText(raw: any): string | null {
  if (!raw) return null;
  let val = raw;
  if (typeof val === "string") {
    try {
      val = JSON.parse(val);
    } catch {
      return val;
    }
  }
  if (typeof val === "string") return val;
  if (Array.isArray(val)) {
    const textItem = val.find(
      (item: any) => item?.type === "text" && typeof item?.text === "string",
    );
    if (textItem) return textItem.text;
  }
  if (typeof val === "object" && val?.type === "text" && val?.text) {
    return val.text;
  }
  return typeof raw === "string" ? raw : JSON.stringify(raw);
}

function parseCompletedResult(content: any[]): CompletedDisplay | null {
  if (!content || content.length < 2) return null;
  const output = content[1]?.data?.output;
  if (!output) return null;
  const text = extractPlainText(output);
  if (!text) return null;
  if (text.startsWith("Error:") || text.includes("交互超时")) {
    return { prefix: "", value: text };
  }
  return formatCompletedDisplay(text);
}

export default function InteractiveChoice(props: {
  data: { content: any[]; status?: string };
}) {
  const { styles } = useStyles();
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [editableText, setEditableText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const content = props.data?.content;
  const cardData = useMemo(() => parseCardArgs(content), [content]);
  const completedResult = useMemo(
    () => parseCompletedResult(content),
    [content],
  );
  const isCompleted = completedResult !== null;

  const handleConfirm = useCallback(async () => {
    if (selectedIndex === null || !cardData) return;

    const option = cardData.options[selectedIndex];
    let resultText: string;
    if (option.type === "fixed") {
      resultText = `用户选择的是${option.label}`;
    } else {
      resultText = `用户选择的是其他，补充内容为${editableText}`;
    }

    setSubmitting(true);
    setSubmitError(null);

    try {
      const sessionId = window.currentSessionId || "";
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const token = getApiToken();
      if (token) headers.Authorization = `Bearer ${token}`;

      const res = await fetch(getApiUrl("/interaction"), {
        method: "POST",
        headers,
        body: JSON.stringify({
          session_id: sessionId,
          result: resultText,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
    } catch (e: any) {
      setSubmitError(e.message || "提交失败");
    } finally {
      setSubmitting(false);
    }
  }, [selectedIndex, editableText, cardData]);

  if (!cardData) return null;

  const selectedOption =
    selectedIndex !== null ? cardData.options[selectedIndex] : null;
  const isEditable = selectedOption?.type === "editable";
  const canConfirm =
    selectedIndex !== null &&
    (!isEditable || editableText.trim().length > 0) &&
    !submitting;

  return (
    <Card className={styles.container} bordered={false}>
      <div className={styles.markdownSection}>
        <XMarkdown>{cardData.text}</XMarkdown>
      </div>

      {isCompleted ? (
        <div className={styles.confirmedBanner}>
          <CheckCircleFilled style={{ color: "#52c41a", fontSize: 16 }} />
          {completedResult!.prefix ? (
            <Typography.Text>
              <span className={styles.confirmedPrefix}>
                {completedResult!.prefix}
              </span>
              <span className={styles.confirmedValue}>
                {completedResult!.value}
              </span>
            </Typography.Text>
          ) : (
            <Typography.Text>{completedResult!.value}</Typography.Text>
          )}
        </div>
      ) : (
        <>
          <div className={styles.optionsSection}>
            <Typography.Text className={styles.optionsLabel}>
              请选择：
            </Typography.Text>
            <Radio.Group
              value={selectedIndex}
              onChange={(e) => {
                setSelectedIndex(e.target.value);
                setEditableText("");
              }}
              disabled={submitting}
            >
              <Space wrap size="middle">
                {cardData.options.map((opt, idx) => (
                  <Radio.Button key={idx} value={idx}>
                    {opt.label}
                  </Radio.Button>
                ))}
              </Space>
            </Radio.Group>

            {isEditable && (
              <Input.TextArea
                className={styles.editableInput}
                placeholder={selectedOption!.label}
                value={editableText}
                onChange={(e) => setEditableText(e.target.value)}
                autoSize={{ minRows: 2, maxRows: 6 }}
                disabled={submitting}
              />
            )}
          </div>

          <Button
            className={styles.confirmBtn}
            type="primary"
            block
            loading={submitting}
            disabled={!canConfirm}
            onClick={handleConfirm}
          >
            确认
          </Button>

          {submitError && (
            <Typography.Text type="danger" style={{ marginTop: 8 }}>
              {submitError}
            </Typography.Text>
          )}
        </>
      )}
    </Card>
  );
}
