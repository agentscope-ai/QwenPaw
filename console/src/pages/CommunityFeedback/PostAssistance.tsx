import ReactMarkdown from "react-markdown";
import { externalLinkMarkdownComponents } from "@/components/Markdown/externalLinkComponents";
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  Select,
  Space,
  Typography,
  Collapse,
  Popover,
} from "antd";
import {
  Sparkles,
  ImagePlus,
  FileSearch,
  Upload,
  SlidersHorizontal,
  Paperclip,
  ArrowLeft,
  Send,
  UserRound,
  FileInput,
} from "lucide-react";
import type { ReportScreenshots } from "./useReportScreenshots";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api/modules/agents";
import { chatApi } from "@/api/modules/chat";
import {
  collectCommunityDiagnostics,
  generateCommunityReport,
  type DiagnosticEvidence,
  type ReportResource,
} from "@/api/modules/communityReport";
import { redactReportText } from "./reportPrivacy";
import { ScreenshotEditor } from "./ScreenshotEditor";
import styles from "./index.module.less";

import type { AssistantSession } from "./writingSession";

interface Props {
  sessionState?: AssistantSession;
  onSessionChange: (state: AssistantSession) => void;
  screenshots: ReportScreenshots;
  resources: ReportResource[];
  articleType: string;
  draft: string;
  instructions: string;
  onInstructions: (value: string) => void;
  onInsertImage: (image: string, index: number) => Promise<void>;
  onApply: (text: string) => void;
  onBusy: (busy: boolean) => void;
}

export function PostAssistance({
  sessionState,
  onSessionChange,
  resources,
  screenshots,
  articleType,
  draft,
  instructions,
  onInstructions,
  onInsertImage,
  onApply,
  onBusy,
}: Props) {
  const { t } = useTranslation();
  const [language, setLanguage] = useState<"auto" | "zh" | "en">(
    sessionState?.language || "auto",
  );
  const [writingStyle, setWritingStyle] = useState<
    "auto" | "concise" | "detailed"
  >(sessionState?.writingStyle || "auto");
  const [materialsOpen, setMaterialsOpen] = useState<string[]>([]);
  const [publicImages, setPublicImages] = useState<Record<string, string>>(
    sessionState?.publicImages || {},
  );
  const [insertedImages, setInsertedImages] = useState<Record<string, string>>(
    sessionState?.insertedImages || {},
  );
  const question = articleType === "question";
  const [evidence, setEvidence] = useState<DiagnosticEvidence[]>(
    sessionState?.evidence || [],
  );
  const [warnings, setWarnings] = useState<string[]>(
    sessionState?.warnings || [],
  );
  const [agents, setAgents] = useState<{ value: string; label: string }[]>([]);
  const [sessions, setSessions] = useState<{ value: string; label: string }[]>(
    [],
  );
  const [agent, setAgent] = useState<string | undefined>(sessionState?.agent);
  const [session, setSession] = useState(sessionState?.session || "");
  const [minutes, setMinutes] = useState(sessionState?.minutes || 60);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState<"collect" | "generate" | "image">();
  const [error, setError] = useState("");
  const [result, setResult] = useState(sessionState?.result || "");
  const [history, setHistory] = useState<
    { role: "user" | "assistant"; content: string }[]
  >(sessionState?.history || []);
  const [writingAgent, setWritingAgent] = useState<string | undefined>(
    sessionState?.writingAgent,
  );
  const [writingAgents, setWritingAgents] = useState<
    { value: string; label: string }[]
  >([]);
  const [pendingText, setPendingText] = useState("");
  const resultPanel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const conversation = resultPanel.current?.parentElement;
    if (conversation) conversation.scrollTop = conversation.scrollHeight;
  }, [history.length, pendingText, busy]);
  const { images, setImages } = screenshots;
  const imageInput = useRef<HTMLInputElement>(null);
  const logInput = useRef<HTMLInputElement>(null);
  const disabled = !!busy || screenshots.loading;
  useEffect(() => setReviewed(false), [images]);
  const previousImageCount = useRef(images.length);
  useEffect(() => {
    if (images.length > previousImageCount.current)
      setMaterialsOpen(["materials"]);
    previousImageCount.current = images.length;
  }, [images.length]);
  useEffect(() => {
    onSessionChange({
      language,
      writingStyle,
      history,
      result,
      writingAgent,
      agent,
      session,
      minutes,
      evidence,
      warnings,
      publicImages,
      insertedImages,
    });
  }, [
    onSessionChange,
    language,
    writingStyle,
    history,
    result,
    writingAgent,
    agent,
    session,
    minutes,
    evidence,
    warnings,
    publicImages,
    insertedImages,
  ]);
  const operation = useRef<AbortController>();
  const mounted = useRef(true);
  const hasMaterials =
    evidence.some((item) => item.content.trim()) || images.length > 0;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      operation.current?.abort();
    };
  }, []);
  useEffect(() => {
    let active = true;
    agentsApi
      .listAgents()
      .then((value) => {
        if (active) {
          setWritingAgents(
            value.agents
              .filter((item) => item.enabled && item.backend === "qwenpaw")
              .map((item) => ({
                value: item.id,
                label: `${item.name} · ${
                  item.active_model?.model ||
                  t("communityAssist.inheritedModel")
                }`,
              })),
          );
          setAgents(
            value.agents
              .filter((item) => item.enabled)
              .map((item) => ({ value: item.id, label: item.name })),
          );
        }
      })
      .catch(() => {
        if (active) setError(t("communityAssist.contextFailed"));
      });
    return () => {
      active = false;
    };
  }, [t]);
  const previousAgent = useRef(agent);
  useEffect(() => {
    let active = true;
    if (previousAgent.current !== agent) setSession("");
    previousAgent.current = agent;
    setSessions([]);
    chatApi
      .listChats({ agentId: agent })
      .then((value) => {
        if (active)
          setSessions(
            value.map((item) => ({
              value: item.session_id,
              label: item.name || item.session_id,
            })),
          );
      })
      .catch(() => {
        if (active) setError(t("communityAssist.contextFailed"));
      });
    return () => {
      active = false;
    };
  }, [agent, t]);
  const resourceKeys = resources
    .map((item) => `${item.origin.resource_type}:${item.origin.resource_id}`)
    .sort()
    .join("|");
  const evidenceContext = JSON.stringify([
    agent,
    session,
    minutes,
    resourceKeys,
  ]);
  const previousEvidenceContext = useRef(evidenceContext);
  useEffect(() => {
    if (previousEvidenceContext.current !== evidenceContext) {
      setEvidence([]);
      setWarnings([]);
      setReviewed(false);
    }
    previousEvidenceContext.current = evidenceContext;
  }, [evidenceContext]);
  const start = (kind: "collect" | "generate" | "image") => {
    const controller = new AbortController();
    operation.current = controller;
    setBusy(kind);
    onBusy(true);
    setError("");
    return controller;
  };
  const finish = (controller: AbortController) => {
    if (operation.current !== controller) return;
    operation.current = undefined;
    if (mounted.current) {
      setBusy(undefined);
      onBusy(false);
    }
  };
  const cancel = () => {
    operation.current?.abort();
    setPendingText("");
    operation.current = undefined;
    setBusy(undefined);
    onBusy(false);
  };
  const valid = (controller: AbortController) =>
    mounted.current &&
    operation.current === controller &&
    !controller.signal.aborted;
  const collect = async () => {
    const controller = start("collect");
    try {
      const data = await collectCommunityDiagnostics(
        resources.map((item) => item.origin),
        minutes,
        session,
        agent,
        controller.signal,
      );
      if (valid(controller)) {
        setEvidence(data.evidence);
        setWarnings(data.warnings);
        setReviewed(false);
      }
    } catch {
      if (valid(controller)) setError(t("communityAssist.collectFailed"));
    } finally {
      finish(controller);
    }
  };
  const generate = async () => {
    const userText =
      instructions.trim() || t("communityAssist.useDraftMaterials");
    setMaterialsOpen([]);
    setPendingText(userText);
    const controller = start("generate");
    try {
      const primary = resources[0];
      const data = await generateCommunityReport(
        {
          agent_id: writingAgent,
          history: history.slice(-12).map((turn) => ({
            ...turn,
            content: redactReportText(turn.content),
          })),
          resource_name: primary?.name || t("communityPage.title"),
          resource_type: primary?.origin.resource_type || "plugin",
          installed_version: primary?.origin.installed_version || "",
          article_type: articleType,
          resource_context: redactReportText(
            JSON.stringify(
              resources.map((item) => ({
                name: item.name,
                origin: item.origin,
                description: item.description,
              })),
            ).slice(0, 6000),
          ),
          draft: redactReportText(result || draft),
          instructions: redactReportText(userText),
          writing_style: writingStyle,
          logs: redactReportText(
            evidence
              .map((item) => `[${item.id}]\n${item.content}`)
              .join("\n\n"),
          ),
          screenshots: images.map((item) => ({ data_url: item.value })),
          materials_reviewed: reviewed,
          language,
        },
        controller.signal,
      );
      if (valid(controller)) {
        setResult(data.report);
        setHistory((current) => [
          ...current,
          { role: "user", content: userText },
          { role: "assistant", content: data.report },
        ]);
        onInstructions("");
      }
    } catch (err) {
      if (valid(controller))
        setError(
          t(
            err instanceof Error && err.message.includes("image_model_required")
              ? "communityAssist.imageModelRequired"
              : err instanceof Error &&
                err.message.includes("model_not_available")
              ? "communityReport.noModel"
              : "communityReport.generateFailed",
          ),
        );
    } finally {
      setPendingText("");
      finish(controller);
    }
  };
  const readFile = async (file: File) => {
    const controller = start("image");
    try {
      if (file.size > 128 * 1024) throw new Error("logTooLarge");
      const text = await file.text();
      if (text.length > 24000) throw new Error("logTooLarge");
      if (valid(controller))
        setEvidence((current) => [
          ...current.filter((item) => item.id !== "manual"),
          { id: "manual", content: redactReportText(text) },
        ]);
      if (valid(controller)) setReviewed(false);
    } catch {
      if (valid(controller)) setError(t("communityReport.logTooLarge"));
    } finally {
      finish(controller);
    }
  };
  const totalLength = evidence.reduce(
    (sum, item) => sum + item.content.length + item.id.length + 4,
    0,
  );
  return (
    <div className={styles.assistance}>
      <header className={styles.assistantHeader}>
        <div className={styles.assistHeading}>
          <Sparkles size={18} />
          <strong>
            {t(
              question
                ? "communityAssist.improveQuestion"
                : "communityAssist.improveArticle",
            )}
          </strong>
        </div>
        <Popover
          trigger="click"
          placement="bottomRight"
          title={t("communityAssist.writingSettings")}
          content={
            <div className={styles.assistantSettings}>
              <div className={styles.field}>
                <label htmlFor="community-writing-agent">
                  {t("communityAssist.writingAgent")}
                </label>
                <Select
                  id="community-writing-agent"
                  aria-label={t("communityAssist.writingAgent")}
                  value={writingAgent}
                  allowClear
                  disabled={disabled}
                  placeholder={t("communityAssist.currentAgentModel")}
                  options={writingAgents}
                  onChange={(value) => {
                    setWritingAgent(value);
                    setReviewed(false);
                  }}
                />
                <p className={styles.hint}>
                  {t("communityAssist.modelSource")}
                </p>
              </div>
              <div className={styles.writingPreferences}>
                <Select
                  aria-label={t("communityAssist.outputLanguage")}
                  value={language}
                  disabled={disabled}
                  onChange={setLanguage}
                  options={["auto", "zh", "en"].map((value) => ({
                    value,
                    label: t(`communityAssist.language_${value}`),
                  }))}
                />
                <Select
                  aria-label={t("communityAssist.writingStyle")}
                  value={writingStyle}
                  disabled={disabled}
                  onChange={setWritingStyle}
                  options={["auto", "concise", "detailed"].map((value) => ({
                    value,
                    label: t(`communityAssist.style_${value}`),
                  }))}
                />
              </div>
            </div>
          }
        >
          <Button
            type="text"
            icon={<SlidersHorizontal size={16} />}
            aria-label={t("communityAssist.writingSettings")}
          >
            {t("communityAssist.writingSettings")}
          </Button>
        </Popover>
      </header>
      <section
        className={styles.writingConversation}
        hidden={materialsOpen.length > 0}
        aria-label={t("communityAssist.conversation")}
        aria-live="polite"
      >
        {history.length === 0 && busy !== "generate" && (
          <div className={styles.conversationEmpty}>
            <Sparkles size={28} aria-hidden="true" />
            <strong>{t("communityAssist.chatStart")}</strong>
            <p>{t("communityAssist.chatEmpty")}</p>
          </div>
        )}
        {history.map((turn, index) => (
          <div
            key={index}
            className={
              turn.role === "user" ? styles.userTurn : styles.assistantTurn
            }
          >
            <div className={styles.turnHeader}>
              <span className={styles.turnIdentity}>
                <span className={styles.turnAvatar} aria-hidden="true">
                  {turn.role === "user" ? (
                    <UserRound size={16} />
                  ) : (
                    <Sparkles size={16} />
                  )}
                </span>
                <strong>
                  {t(
                    turn.role === "user"
                      ? "communityAssist.you"
                      : "communityAssist.assistant",
                  )}
                </strong>
              </span>
              {turn.role === "assistant" && (
                <Button
                  type="primary"
                  className={styles.applyDraftButton}
                  icon={<FileInput size={16} aria-hidden="true" />}
                  disabled={disabled}
                  onClick={() => onApply(turn.content)}
                >
                  {t("communityAssist.apply")}
                </Button>
              )}
            </div>
            <div className={styles.turnContent}>
              <ReactMarkdown components={externalLinkMarkdownComponents}>
                {turn.content}
              </ReactMarkdown>
            </div>
          </div>
        ))}
        {busy === "generate" && (
          <>
            <div className={styles.userTurn}>
              <div className={styles.turnHeader}>
                <span className={styles.turnIdentity}>
                  <span className={styles.turnAvatar} aria-hidden="true">
                    <UserRound size={16} />
                  </span>
                  <strong>{t("communityAssist.you")}</strong>
                </span>
              </div>
              <p className={styles.turnContent}>{pendingText}</p>
            </div>
            <div className={styles.assistantTurn} role="status">
              <div className={styles.turnHeader}>
                <span className={styles.turnIdentity}>
                  <span className={styles.turnAvatar} aria-hidden="true">
                    <Sparkles size={16} />
                  </span>
                  <strong>{t("communityAssist.assistant")}</strong>
                </span>
              </div>
              <p className={styles.turnContent}>
                {t("communityReport.generating")}
              </p>
            </div>
          </>
        )}
        <div ref={resultPanel} />
      </section>
      <section
        className={styles.materialWorkspace}
        hidden={materialsOpen.length === 0}
        aria-label={t("communityAssist.materials")}
      >
        <div className={styles.materialHeader}>
          <Button
            type="text"
            icon={<ArrowLeft size={16} />}
            onClick={() => setMaterialsOpen([])}
          >
            {t("communityAssist.backToChat")}
          </Button>
          <strong>{t("communityAssist.materials")}</strong>
        </div>
        <Collapse
          ghost
          className={styles.diagnostics}
          items={[
            {
              key: "diagnostics",
              label: (
                <span className={styles.resourceLabel}>
                  <FileSearch size={16} />
                  {t("communityAssist.diagnosticOptional")}
                </span>
              ),
              children: (
                <>
                  <div className={styles.diagnosticFields}>
                    <Select
                      aria-label={t("communityAssist.agent")}
                      placeholder={t("communityAssist.currentAgent")}
                      style={{ width: "100%" }}
                      allowClear
                      value={agent}
                      options={agents}
                      disabled={disabled}
                      onChange={setAgent}
                    />
                    <Select
                      aria-label={t("communityAssist.session")}
                      placeholder={t("communityAssist.session")}
                      style={{ width: "100%" }}
                      allowClear
                      value={session || undefined}
                      options={sessions}
                      disabled={disabled}
                      onChange={(value) => setSession(value || "")}
                    />
                    <Select
                      aria-label={t("communityAssist.timeRange")}
                      value={minutes}
                      disabled={disabled}
                      onChange={setMinutes}
                      options={[15, 60, 1440].map((value) => ({
                        value,
                        label: t(`communityAssist.minutes${value}`),
                      }))}
                    />
                    <Button
                      disabled={disabled}
                      loading={busy === "collect"}
                      onClick={() => void collect()}
                    >
                      {t("communityAssist.collect")}
                    </Button>
                  </div>
                  {warnings.map((value) => (
                    <Alert
                      key={value}
                      type="info"
                      showIcon
                      message={t(`communityAssist.${value}`)}
                    />
                  ))}
                  <Typography.Text type="secondary">
                    {t("communityAssist.evidenceHelp")}
                  </Typography.Text>
                  {evidence.map((item, index) => (
                    <div key={item.id} className={styles.field}>
                      <Space>
                        <label htmlFor={`evidence-${item.id}`}>
                          {t(`communityAssist.evidence_${item.id}`)}
                        </label>
                        <Button
                          size="small"
                          disabled={disabled}
                          onClick={() => {
                            setEvidence((current) =>
                              current.filter((_, i) => i !== index),
                            );
                            setReviewed(false);
                          }}
                        >
                          {t("communityAssist.remove")}
                        </Button>
                      </Space>
                      <Input.TextArea
                        id={`evidence-${item.id}`}
                        value={item.content}
                        rows={4}
                        disabled={disabled}
                        maxLength={24000}
                        onChange={(event) => {
                          setEvidence((current) =>
                            current.map((entry, i) =>
                              i === index
                                ? {
                                    ...entry,
                                    content: redactReportText(
                                      event.target.value,
                                    ),
                                  }
                                : entry,
                            ),
                          );
                          setReviewed(false);
                        }}
                      />
                    </div>
                  ))}
                  <input
                    ref={logInput}
                    type="file"
                    accept=".txt,.log,.json"
                    hidden
                    disabled={disabled}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      event.target.value = "";
                      if (file) void readFile(file);
                    }}
                  />
                  <Button
                    size="small"
                    icon={<Upload size={14} />}
                    disabled={disabled}
                    onClick={() => logInput.current?.click()}
                  >
                    {t("communityReport.chooseLog")}
                  </Button>
                </>
              ),
            },
          ]}
        />
        <section className={styles.imageMaterials}>
          <div className={styles.sectionLabel}>
            <span>{t("communityAssist.referenceImages")}</span>
            <span>{images.length} / 2</span>
          </div>
          <div
            role="group"
            aria-label={t("communityAssist.referenceImages")}
            tabIndex={disabled || images.length >= 2 ? -1 : 0}
            className={styles.pasteArea}
            aria-disabled={disabled || images.length >= 2}
            onClick={(event) => {
              if (!disabled && images.length < 2) event.currentTarget.focus();
            }}
            onDragOver={(event) => {
              if (event.dataTransfer.types.includes("Files"))
                event.preventDefault();
            }}
            onDrop={(event) => {
              event.preventDefault();
              if (!disabled)
                void screenshots.add(Array.from(event.dataTransfer.files));
            }}
          >
            <ImagePlus size={23} />
            <strong>
              {t(
                screenshots.loading
                  ? "communityAssist.readingImage"
                  : "communityAssist.pasteImage",
              )}
            </strong>
            <span>{t("communityAssist.pasteImageHint")}</span>
            <Button
              size="small"
              icon={<Upload size={14} />}
              disabled={disabled || images.length >= 2}
              onClick={(event) => {
                event.stopPropagation();
                imageInput.current?.click();
              }}
            >
              {t("communityAssist.chooseImage")}
            </Button>
          </div>
          <input
            ref={imageInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            hidden
            disabled={disabled || images.length >= 2}
            onChange={(event) => {
              const files = Array.from(event.target.files || []);
              event.target.value = "";
              void screenshots.add(files);
            }}
          />
          <p className={styles.hint}>{t("communityAssist.imagePrivacy")}</p>
          {screenshots.error && (
            <Alert type="error" showIcon message={t(screenshots.error)} />
          )}
          {!!images.length && (
            <Typography.Text type="secondary">
              {t("communityReport.imageHelp")}
            </Typography.Text>
          )}
          {images.map((item, index) => (
            <div key={item.id} className={styles.field}>
              <ScreenshotEditor
                key={item.id}
                index={index}
                source={item.source}
                value={item.value}
                disabled={disabled}
                onChange={(value) => {
                  setImages((current) =>
                    current.map((entry) =>
                      entry.id === item.id ? { ...entry, value } : entry,
                    ),
                  );
                  setReviewed(false);
                }}
                onRemove={() => {
                  setImages((current) =>
                    current.filter((entry) => entry.id !== item.id),
                  );
                  setReviewed(false);
                }}
              />
              <div className={styles.consentAction}>
                <Checkbox
                  checked={publicImages[item.id] === item.value}
                  disabled={disabled}
                  onChange={(event) =>
                    setPublicImages((current) => ({
                      ...current,
                      [item.id]: event.target.checked ? item.value : "",
                    }))
                  }
                >
                  {t("communityAssist.publicImages")}
                </Checkbox>
                <Button
                  disabled={
                    disabled ||
                    publicImages[item.id] !== item.value ||
                    insertedImages[item.id] === item.value
                  }
                  onClick={async () => {
                    const controller = start("image");
                    try {
                      await onInsertImage(item.value, index);
                      if (valid(controller))
                        setInsertedImages((current) => ({
                          ...current,
                          [item.id]: item.value,
                        }));
                    } catch {
                      if (valid(controller))
                        setError(t("communityAssist.imageUploadFailed"));
                    } finally {
                      finish(controller);
                    }
                  }}
                >
                  {t(
                    insertedImages[item.id] === item.value
                      ? "communityAssist.imageInserted"
                      : "communityAssist.insertImage",
                  )}
                </Button>
              </div>
            </div>
          ))}
        </section>
      </section>
      <div className={styles.chatComposer}>
        {totalLength > 24000 && (
          <Alert type="warning" message={t("communityReport.logTooLarge")} />
        )}
        {error && <Alert type="error" showIcon message={error} />}
        <div className={styles.generateActions}>
          <div className={styles.field}>
            <label htmlFor="community-writing-instructions">
              {t(
                history.length
                  ? "communityAssist.nextMessage"
                  : "communityAssist.instructions",
              )}
            </label>
            <Input.TextArea
              id="community-writing-instructions"
              value={instructions}
              autoSize={{ minRows: 2, maxRows: 4 }}
              maxLength={2000}
              disabled={disabled}
              placeholder={t(
                question
                  ? "communityAssist.questionIdea"
                  : "communityAssist.articleIdea",
              )}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  (event.metaKey || event.ctrlKey) &&
                  !disabled &&
                  instructions.trim() &&
                  (!hasMaterials || reviewed) &&
                  totalLength <= 24000 &&
                  (result || draft).length <= 32000
                ) {
                  event.preventDefault();
                  void generate();
                }
              }}
              onChange={(event) => onInstructions(event.target.value)}
            />
          </div>

          {hasMaterials && (
            <Checkbox
              checked={reviewed}
              disabled={disabled}
              onChange={(event) => setReviewed(event.target.checked)}
            >
              {t("communityReport.reviewMaterials")}
            </Checkbox>
          )}

          {hasMaterials && !reviewed && (
            <p className={styles.hint}>{t("communityAssist.reviewHint")}</p>
          )}
          <div className={styles.chatToolbar}>
            <Button
              type="text"
              icon={<Paperclip size={16} />}
              aria-expanded={materialsOpen.length > 0}
              onClick={() =>
                setMaterialsOpen(materialsOpen.length ? [] : ["materials"])
              }
            >
              {t("communityAssist.attachments")}
              {hasMaterials ? ` · ${images.length + evidence.length}` : ""}
            </Button>
            <Button
              type="primary"
              icon={<Send size={14} />}
              disabled={
                disabled ||
                !(
                  instructions.trim() ||
                  (!history.length && (draft.trim() || hasMaterials))
                ) ||
                (result || draft).length > 32000 ||
                totalLength > 24000 ||
                (hasMaterials && !reviewed)
              }
              loading={busy === "generate"}
              onClick={() => void generate()}
            >
              {t("communityAssist.sendMessage")}
            </Button>
            {busy && (
              <Button onClick={cancel}>
                {t("communityReport.cancelGeneration")}
              </Button>
            )}
          </div>
          {busy && busy !== "generate" && (
            <Typography.Text type="secondary" role="status">
              {t("communityReport.modelHelp")}
            </Typography.Text>
          )}
        </div>
      </div>
    </div>
  );
}
