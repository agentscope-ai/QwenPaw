import { useEffect, useId, useRef, useState } from "react";
import { Alert, Button, Checkbox, Collapse, Input, Modal, Space } from "antd";
import { useTranslation } from "react-i18next";
import { generateCommunityReport } from "@/api/modules/communityReport";
import type { InstallationOrigin } from "@/api/types/community";
import { copyText } from "@/utils/clipboard";
import { PostComposer } from "./PostComposer";
import { useAppMessage } from "@/hooks/useAppMessage";
import { ScreenshotEditor } from "./ScreenshotEditor";
import { readReportScreenshot, redactReportText } from "./reportPrivacy";
import styles from "./index.module.less";

interface Props {
  open: boolean;
  onClose: () => void;
  origin: InstallationOrigin;
  resourceName: string;
}

interface Screenshot {
  id: string;
  source: string;
  value: string;
}

// Keeps sanitized text when the modal is reopened during this page visit.
// Images and model inputs are never written to browser storage or a session.
const drafts = new Map<string, { draft: string; logs: string }>();

export function ResourceReportModal({
  open,
  onClose,
  origin,
  resourceName,
}: Props) {
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const id = useId();
  const language = (i18n.resolvedLanguage || i18n.language).startsWith("zh")
    ? "zh"
    : "en";
  const resourceKey = `${origin.resource_type}:${origin.resource_id}:${
    origin.installed_version || ""
  }`;
  const [composeOpen, setComposeOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [logs, setLogs] = useState("");
  const [screenshots, setScreenshots] = useState<Screenshot[]>([]);
  const [reviewed, setReviewed] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [manualCopy, setManualCopy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [readingImage, setReadingImage] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef<AbortController | null>(null);
  const active = useRef(false);
  const draftKey = useRef<string | null>(null);
  const editRevision = useRef(0);
  const hasMaterials = !!logs.trim() || screenshots.length > 0;

  useEffect(() => {
    active.current = open;
    if (open) {
      const cached = drafts.get(resourceKey);
      draftKey.current = resourceKey;
      setDraft(
        cached?.draft ??
          redactReportText(
            t("communityReport.template", {
              name: resourceName,
              type: origin.resource_type,
              version: origin.installed_version || t("communityReport.unknown"),
            }),
          ),
      );
      setLogs(cached?.logs ?? "");
      setScreenshots([]);
      setReviewed(false);
      setConfirmed(false);
      setManualCopy(false);
      setError("");
    }
    return () => {
      active.current = false;
      editRevision.current += 1;
      generation.current?.abort();
      generation.current = null;
      setGenerating(false);
    };
    // Locale changes do not replace a report that the user is editing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, resourceKey]);

  const updateDraft = (text: string) => {
    if (text.length > 32_000) {
      setError(t("communityReport.reportTooLong"));
      return;
    }
    const next = redactReportText(text);
    setDraft(next);
    setConfirmed(false);
    setManualCopy(false);
    if (draftKey.current) drafts.set(draftKey.current, { draft: next, logs });
  };
  const updateLogs = (text: string) => {
    const next = redactReportText(text);
    setLogs(next);
    setReviewed(false);
    if (draftKey.current) drafts.set(draftKey.current, { draft, logs: next });
  };
  const cancel = () => {
    generation.current?.abort();
    generation.current = null;
    setGenerating(false);
  };

  const generate = async () => {
    if (generation.current || !draft.trim() || (hasMaterials && !reviewed))
      return;
    const controller = new AbortController();
    generation.current = controller;
    setGenerating(true);
    setError("");
    try {
      const result = await generateCommunityReport(
        {
          resource_name: redactReportText(resourceName),
          resource_type: origin.resource_type,
          installed_version: redactReportText(origin.installed_version || ""),
          draft: redactReportText(draft),
          logs: redactReportText(logs),
          screenshots: screenshots.map((image) => ({ data_url: image.value })),
          materials_reviewed: reviewed,
          language,
        },
        controller.signal,
      );
      if (
        generation.current === controller &&
        !controller.signal.aborted &&
        active.current
      ) {
        updateDraft(result.report);
      }
    } catch (error) {
      if (!controller.signal.aborted && active.current) {
        const code = error instanceof Error ? error.message : "";
        setError(
          code.includes("model_not_available")
            ? t("communityReport.noModel")
            : t("communityReport.generateFailed"),
        );
      }
    } finally {
      if (generation.current === controller) {
        generation.current = null;
        setGenerating(false);
      }
    }
  };

  const readLogs = async (file: File) => {
    const revision = editRevision.current;
    if (file.size > 128 * 1024) {
      setError(t("communityReport.logTooLarge"));
      return;
    }
    try {
      const text = await file.text();
      if (active.current && revision === editRevision.current) {
        if (text.length > 24_000) setError(t("communityReport.logTooLarge"));
        else updateLogs(text);
      }
    } catch {
      setError(t("communityReport.readFailed"));
    }
  };

  const readImage = async (file: File) => {
    if (screenshots.length >= 2 || readingImage) return;
    const revision = editRevision.current;
    setReadingImage(true);
    try {
      const value = await readReportScreenshot(file);
      if (active.current && revision === editRevision.current) {
        setScreenshots((current) => [
          ...current,
          { id: crypto.randomUUID(), source: value, value },
        ]);
        setReviewed(false);
      }
    } catch {
      if (active.current) setError(t("communityReport.invalidImage"));
    } finally {
      setReadingImage(false);
    }
  };

  const copyReport = async () => {
    try {
      await copyText(draft);
      message.success(t("communityReport.copied"));
    } catch {
      setError(t("communityReport.copyFailed"));
      setManualCopy(true);
    }
  };

  if (composeOpen)
    return (
      <PostComposer
        origin={origin}
        resourceName={resourceName}
        initialBody={draft}
        onClose={() => setComposeOpen(false)}
      />
    );

  return (
    <Modal
      open={open}
      onCancel={() => {
        cancel();
        onClose();
      }}
      title={t("communityReport.title", { name: resourceName })}
      width={860}
      maskClosable={false}
      footer={
        <Space wrap>
          <Button
            onClick={() => {
              cancel();
              onClose();
            }}
          >
            {t("communityReport.close")}
          </Button>
          <Button
            disabled={generating || !confirmed || !draft.trim()}
            onClick={() => void copyReport()}
          >
            {t("communityReport.copy")}
          </Button>
          <Button
            type="primary"
            disabled={!confirmed || !draft.trim() || generating}
            onClick={() => {
              setComposeOpen(true);
            }}
          >
            {t("communityReport.continue")}
          </Button>
        </Space>
      }
    >
      <div className={styles.content}>
        <Alert type="info" showIcon message={t("communityReport.localHelp")} />
        <div className={styles.field}>
          <label htmlFor={`${id}-draft`}>{t("communityReport.report")}</label>
          <Input.TextArea
            id={`${id}-draft`}
            value={draft}
            rows={14}
            maxLength={32_000}
            disabled={generating}
            onChange={(event) => updateDraft(event.target.value)}
          />
          <p className={styles.hint}>{t("communityReport.redactionHelp")}</p>
        </div>
        <Collapse
          items={[
            {
              key: "materials",
              label: t("communityReport.materials"),
              children: (
                <div className={styles.materials}>
                  <div className={styles.field}>
                    <label htmlFor={`${id}-logs`}>
                      {t("communityReport.logs")}
                    </label>
                    <Input.TextArea
                      id={`${id}-logs`}
                      value={logs}
                      rows={5}
                      maxLength={24_000}
                      disabled={generating}
                      onChange={(event) => updateLogs(event.target.value)}
                    />
                    <label className={styles.fileInput}>
                      {t("communityReport.chooseLog")}
                      <input
                        type="file"
                        accept=".txt,.log,.json"
                        disabled={generating}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          event.target.value = "";
                          if (file) void readLogs(file);
                        }}
                      />
                    </label>
                    <Button
                      disabled={!logs.trim() || generating}
                      onClick={() =>
                        updateDraft(
                          `${draft}\n\n${t(
                            "communityReport.logsHeading",
                          )}\n\n${logs}`,
                        )
                      }
                    >
                      {t("communityReport.insertLogs")}
                    </Button>
                  </div>
                  <label className={styles.fileInput}>
                    {t("communityReport.chooseImage")}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      disabled={
                        generating || readingImage || screenshots.length >= 2
                      }
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.target.value = "";
                        if (file) void readImage(file);
                      }}
                    />
                  </label>
                  <p className={styles.hint}>
                    {t("communityReport.imageHelp")}
                  </p>
                  {screenshots.map((image, index) => (
                    <ScreenshotEditor
                      key={image.id}
                      index={index}
                      source={image.source}
                      value={image.value}
                      disabled={generating}
                      onChange={(value) => {
                        setScreenshots((current) =>
                          current.map((item) =>
                            item.id === image.id ? { ...item, value } : item,
                          ),
                        );
                        setReviewed(false);
                      }}
                      onRemove={() => {
                        setScreenshots((current) =>
                          current.filter((item) => item.id !== image.id),
                        );
                        setReviewed(false);
                      }}
                    />
                  ))}
                </div>
              ),
            },
          ]}
        />
        {hasMaterials && (
          <Checkbox
            checked={reviewed}
            disabled={generating}
            onChange={(event) => setReviewed(event.target.checked)}
          >
            {t("communityReport.reviewMaterials")}
          </Checkbox>
        )}
        <div className={styles.actions}>
          {generating ? (
            <Button onClick={cancel}>
              {t("communityReport.cancelGeneration")}
            </Button>
          ) : (
            <Button
              disabled={
                !draft.trim() || readingImage || (hasMaterials && !reviewed)
              }
              onClick={() => void generate()}
            >
              {t("communityReport.generate")}
            </Button>
          )}
          <span className={styles.hint} role="status">
            {generating
              ? t("communityReport.generating")
              : t("communityReport.modelHelp")}
          </span>
        </div>
        {error && (
          <Alert
            type="error"
            role="alert"
            message={error}
            closable
            onClose={() => setError("")}
          />
        )}
        {manualCopy && confirmed && (
          <Button
            onClick={() => {
              setManualCopy(false);
            }}
          >
            {t("communityReport.manuallyCopied")}
          </Button>
        )}

        <Checkbox
          checked={confirmed}
          disabled={generating || !draft.trim()}
          onChange={(event) => {
            setConfirmed(event.target.checked);
          }}
        >
          {t("communityReport.confirmReport")}
        </Checkbox>
        <p className={styles.hint}>{t("communityReport.handoffHelp")}</p>
      </div>
    </Modal>
  );
}
