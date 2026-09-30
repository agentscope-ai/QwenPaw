import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  Modal,
  Select,
  Segmented,
  Tag,
  Spin,
} from "antd";
import {
  ArrowLeft,
  MessageCircleQuestion,
  FileText,
  Sparkles,
  Eye,
  Pencil,
  Plus,
  Link2,
  ChevronDown,
} from "lucide-react";
import { useReportScreenshots } from "./useReportScreenshots";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import { externalLinkMarkdownComponents } from "@/components/Markdown/externalLinkComponents";
import {
  type ReportResource,
  reportResourceKey,
} from "@/api/modules/communityReport";
import { PostAssistance } from "./PostAssistance";
import { ResourcePicker } from "./ResourcePicker";
import { communityResourceIdentity } from "@/utils/communityResources";
import { redactReportText } from "./reportPrivacy";
import styles from "./index.module.less";
import { getPostDraft, savePostDraft } from "./postDrafts";
import {
  getWritingSession,
  saveWritingSession,
  removeWritingSession,
  removeWritingDraftSessions,
  writingSessionKey,
  type AssistantSession,
} from "./writingSession";
import { openExternalLink } from "@/utils/openExternalLink";
import { request } from "@/api/request";
import {
  communityConnectionApi,
  type CommunityConnectionStatus,
} from "@/api/modules/community";
import { COMMUNITY_POST_TYPES } from "@/constants/community";
import {
  reserveAuthorizationWindow,
  openAuthorizationUrl,
} from "@/utils/communityAuthorization";
import { communityErrorKey } from "@/utils/communityError";
import type { InstallationOrigin } from "@/api/types/community";

function ComposerFrame({
  page,
  title,
  children,
  footer,
  width,
  onClose,
  busy,
}: {
  page: boolean;
  title: ReactNode;
  children: ReactNode;
  footer: ReactNode;
  width: number;
  onClose: () => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  if (page)
    return (
      <section
        className={styles.composerPage}
        aria-label={t("communityCompose.title")}
      >
        <header className={styles.pageHeader}>
          <Button
            type="text"
            icon={<ArrowLeft size={16} />}
            disabled={busy}
            onClick={onClose}
          >
            {t("communityPage.back")}
          </Button>
          <h1>{title}</h1>
        </header>
        {children}
        {footer && <footer className={styles.pageFooter}>{footer}</footer>}
      </section>
    );
  return (
    <Modal
      open
      title={title}
      className={styles.composerModal}
      width={width}
      style={{ top: 32 }}
      maskClosable={false}
      onCancel={busy ? undefined : onClose}
      footer={footer}
    >
      {children}
    </Modal>
  );
}

export function PostComposer({
  onClose,
  presentation = "modal",
  draftId,
  initialBody = "",
  initialType = "question",
  origin,
  resourceName,
}: {
  onClose: () => void;
  presentation?: "modal" | "page";
  draftId?: string;
  initialBody?: string;
  initialType?: "question" | "discussion";
  origin?: InstallationOrigin;
  resourceName?: string;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CommunityConnectionStatus>();
  const [title, setTitle] = useState(
    initialBody.match(/^#\s+(.+)/)?.[1]?.slice(0, 256) || "",
  );
  const [content, setContent] = useState(initialBody);
  const [type, setType] = useState<string>(initialType);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const savedId = useRef<string | undefined>(draftId);
  const [saveNotice, setSaveNotice] = useState("");
  const [draftUnavailable, setDraftUnavailable] = useState(false);
  const [draftLoading, setDraftLoading] = useState(Boolean(draftId));
  const [richDraft, setRichDraft] = useState(false);
  const [savedKind, setSavedKind] = useState<string>();
  const [published, setPublished] = useState<string>();
  const [assisting, setAssisting] = useState(false);
  const [assistInitialized, setAssistInitialized] = useState(false);
  const [assistBusy, setAssistBusy] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [media, setMedia] = useState<{ url: string; media_id: string }[]>([]);
  const [assistWidth, setAssistWidth] = useState(35);
  const [mobilePane, setMobilePane] = useState("write");
  const [preview, setPreview] = useState(false);
  const [catalog, setCatalog] = useState<ReportResource[]>([]);
  const [resources, setResources] = useState<ReportResource[]>(
    origin ? [{ origin, name: resourceName || origin.resource_id }] : [],
  );
  const screenshots = useReportScreenshots(status?.account?.id);
  const locked =
    busy ||
    assistBusy ||
    screenshots.loading ||
    draftUnavailable ||
    draftLoading;
  const [addingResources, setAddingResources] = useState(false);
  const [loadingResources, setLoadingResources] = useState(false);
  const articleBoard = useRef("discussion");
  const draftOwner = useRef<string>();
  const cacheKey = useRef<string>();
  const [readyKey, setReadyKey] = useState("");
  const [assistantSession, setAssistantSession] = useState<AssistantSession>();
  const onAssistantSession = useCallback(
    (value: AssistantSession) => setAssistantSession(value),
    [],
  );
  const currentKey =
    status?.status === "connected" && status.account
      ? writingSessionKey(
          status.account.id,
          `${draftId || "new"}:${
            origin ? reportResourceKey(origin) : `general:${initialType}`
          }`,
        )
      : "";
  const mounted = useRef(true);
  useEffect(() => {
    if (!currentKey || !status?.account) {
      setConfirmed(false);
      setAssistBusy(false);
      setReadyKey("");
      return;
    }
    let active = true;
    const key = currentKey;
    const account = status.account.id;
    draftOwner.current = account;
    cacheKey.current = key;
    savedId.current = draftId;
    setReadyKey("");
    setConfirmed(false);
    setAssisting(false);
    setAssistInitialized(false);
    setAssistantSession(undefined);
    setAssistBusy(false);
    setSavedKind(undefined);
    setRichDraft(false);
    setDraftUnavailable(false);
    setError(undefined);
    setTitle(initialBody.match(/^#\s+(.+)/)?.[1]?.slice(0, 256) || "");
    setContent(initialBody);
    setType(initialType);
    setInstructions("");
    setMedia([]);
    setResources(
      origin ? [{ origin, name: resourceName || origin.resource_id }] : [],
    );
    setAddingResources(false);
    setPreview(false);
    setAssistWidth(35);
    setMobilePane("write");
    const restore = async () => {
      setDraftLoading(true);
      try {
        const local = getWritingSession(key);
        const saved =
          local || (draftId ? await getPostDraft(account, draftId) : undefined);
        if (!active) return;
        if (saved && "editable" in saved && saved.editable === false) {
          setRichDraft(true);
          setDraftUnavailable(true);
          return;
        }
        savedId.current = draftId || saved?.id;
        if (saved) {
          setTitle(saved.title);
          setContent(saved.content);
          setType(saved.type);
          setResources(saved.resources);
          setInstructions(saved.instructions || "");
          setMedia(saved.media || []);
          if (saved.id) setSavedKind(saved.type);
          if (saved.type !== "question") articleBoard.current = saved.type;
        }
        if (local) {
          setAssisting(local.assisting);
          setAssistInitialized(local.assistInitialized);
          setAssistantSession(local.assistant);
          setAssistWidth(local.assistWidth);
          setMobilePane(local.mobilePane);
          setPreview(local.preview);
          setAddingResources(local.addingResources);
          screenshots.setImages(local.images);
        }
        setReadyKey(key);
      } catch {
        if (active) {
          setDraftUnavailable(true);
          setError("communityDrafts.failed");
        }
      } finally {
        if (active) setDraftLoading(false);
      }
    };
    void restore();
    return () => {
      active = false;
    };
    // Account, draft and resource identity are all represented by currentKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKey]);
  useEffect(() => {
    if (
      currentKey &&
      readyKey === currentKey &&
      !published &&
      !draftUnavailable
    ) {
      saveWritingSession(currentKey, {
        id: savedId.current,
        draftId,
        title,
        content,
        type,
        resources,
        instructions,
        media,
        initialType,
        general: !origin,
        assisting,
        assistInitialized,
        assistWidth,
        mobilePane,
        preview,
        addingResources,
        images: screenshots.images,
        assistant: assistantSession,
      });
    }
  }, [
    currentKey,
    readyKey,
    title,
    content,
    type,
    resources,
    instructions,
    media,
    published,
    draftUnavailable,
    initialType,
    origin,
    assisting,
    assistInitialized,
    assistWidth,
    mobilePane,
    preview,
    addingResources,
    screenshots.images,
    assistantSession,
    savedKind,
  ]);
  const loadResources = async (showPicker = true) => {
    if (showPicker) setAddingResources(true);
    setLoadingResources(true);
    try {
      const data = await request<{ resources: ReportResource[] }>(
        "/community/report/resources",
      );
      if (mounted.current) {
        setCatalog(data.resources);
      }
    } catch (err) {
      if (mounted.current) setError(communityErrorKey(err));
    } finally {
      if (mounted.current) setLoadingResources(false);
    }
  };
  useEffect(() => {
    if (readyKey && (addingResources || assistInitialized))
      void loadResources(false);
    // Refresh installed choices once when a writing session is restored.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readyKey]);
  useEffect(() => {
    mounted.current = true;
    const refresh = () =>
      communityConnectionApi
        .status()
        .then((value) => {
          if (mounted.current) setStatus(value);
        })
        .catch((err) => {
          if (mounted.current) setError(communityErrorKey(err));
        });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, []);
  const login = async () => {
    let popup: Window | null = null;
    setBusy(true);
    setError(undefined);
    try {
      popup = reserveAuthorizationWindow(t("community.waiting"));
      const flow = await communityConnectionApi.start();
      try {
        if (!mounted.current) throw new Error("authorization_cancelled");
        await openAuthorizationUrl(flow.authorize_url, popup);
      } catch (err) {
        await communityConnectionApi.cancel(flow.flow_id).catch(() => {});
        throw err;
      }
    } catch (err) {
      popup?.close();
      if (mounted.current) setError(communityErrorKey(err));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const saveDraft = async () => {
    if (!status?.account || locked) return;
    const account = status.account.id;
    setBusy(true);
    setSaving(true);
    try {
      const saved = await savePostDraft(
        status.account.id,
        {
          title: redactReportText(title),
          content: redactReportText(content),
          type,
          resources,
          instructions: redactReportText(instructions),
          media,
        },
        savedId.current,
      );
      if (!mounted.current || draftOwner.current !== account) return;
      savedId.current = saved.id;
      setSavedKind(type);
      if (cacheKey.current) {
        const session = getWritingSession(cacheKey.current);
        if (session)
          saveWritingSession(cacheKey.current, { ...session, id: saved.id });
      }
      setSaveNotice(
        t("communityDrafts.saved", {
          time: new Date(saved.updatedAt).toLocaleTimeString(),
        }),
      );
      setError(undefined);
    } catch {
      setSaveNotice("");
      setError("communityDrafts.saveFailed");
    } finally {
      if (mounted.current) {
        setBusy(false);
        setSaving(false);
      }
    }
  };
  useEffect(() => {
    setSaveNotice("");
  }, [title, content, type, resources, instructions, media]);
  const publish = async () => {
    if (
      status?.status !== "connected" ||
      !status.account ||
      !confirmed ||
      busy ||
      assistBusy
    )
      return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await request<{ id: string }>("/community/posts", {
        method: "POST",
        body: JSON.stringify({
          title,
          content,
          draft_id: savedId.current,
          media_ids: media
            .filter((item) => content.includes(item.url))
            .map((item) => item.media_id),
          article_type: type,
          account_id: status.account.id,
          origins: resources.map((item) => item.origin),
        }),
      });
      if (cacheKey.current) removeWritingSession(cacheKey.current);
      if (savedId.current)
        removeWritingDraftSessions(status.account.id, savedId.current);
      setPublished(result.id);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setBusy(false);
    }
  };
  const connected = status?.status === "connected";
  const changeType = (next: string) => {
    if (next !== "question") articleBoard.current = next;
    if (savedKind && (savedKind === "question") !== (next === "question")) {
      setError("communityDrafts.kindLocked");
      return;
    }
    setType(next);
    setConfirmed(false);
  };
  const showAssistance = () => {
    setAssistInitialized(true);
    setAssisting(true);
    setMobilePane("assist");
    if (!catalog.length) void loadResources(false);
  };
  return (
    <ComposerFrame
      page={presentation === "page"}
      title={t(
        origin ? "communityFeedback.reportIssue" : "communityCompose.title",
      )}
      width={assisting && connected ? 1120 : 800}
      busy={busy}
      onClose={onClose}
      footer={
        connected && !published ? (
          <div className={styles.publishFooter}>
            <Checkbox
              checked={confirmed}
              disabled={locked}
              onChange={(event) => setConfirmed(event.target.checked)}
            >
              {t("communityCompose.confirm")}
            </Checkbox>
            <div className={styles.footerActions}>
              <span className={styles.hint} role="status">
                {saveNotice || t("communityAssist.draftHelp")}
              </span>
              <Button
                onClick={saveDraft}
                loading={saving}
                disabled={locked || !(title.trim() || content.trim())}
              >
                {t("communityDrafts.save")}
              </Button>
              <Button
                type="primary"
                loading={busy && !saving}
                disabled={
                  !confirmed || !title.trim() || !content.trim() || locked
                }
                onClick={() => void publish()}
              >
                {t("communityCompose.publish")}
              </Button>
            </div>
          </div>
        ) : null
      }
    >
      <div
        className={styles.composer}
        onPasteCapture={(event) => {
          const files = Array.from(event.clipboardData.items)
            .filter(
              (item) => item.kind === "file" && item.type.startsWith("image/"),
            )
            .map((item) => item.getAsFile())
            .filter((file): file is File => !!file);
          if (!files.length || !connected) return;
          event.preventDefault();
          if (locked) return;
          showAssistance();
          void screenshots.add(files);
        }}
      >
        {draftLoading && <Spin />}
        {richDraft && (
          <Alert
            type="info"
            message={t("communityDrafts.richText")}
            action={
              <Button
                onClick={() =>
                  openExternalLink(
                    `https://platform.agentscope.io/community/write?draftId=${encodeURIComponent(
                      draftId || "",
                    )}`,
                  )
                }
              >
                {t("communityDrafts.platformEdit")}
              </Button>
            }
          />
        )}
        {error && (
          <Alert
            type="error"
            message={t(error)}
            description={t("communityCompose.error")}
          />
        )}
        {published ? (
          <Alert
            type="success"
            message={t("communityCompose.published")}
            description={
              <a
                href={`/market?tab=community&post=${encodeURIComponent(
                  published,
                )}`}
              >
                {t("communityCompose.view")}
              </a>
            }
          />
        ) : !status ? (
          <Spin />
        ) : !connected ? (
          <>
            <Alert
              type="info"
              message={t("communityCompose.loginRequired")}
              description={t("communityCompose.loginHelp")}
            />
            <Button type="primary" loading={busy} onClick={() => void login()}>
              {t("communityCompose.login")}
            </Button>
          </>
        ) : (
          <>
            {assisting && (
              <div className={styles.mobilePaneSwitch}>
                <Segmented
                  block
                  aria-label={t("communityAssist.workspace")}
                  value={mobilePane}
                  options={[
                    { value: "write", label: t("communityAssist.edit") },
                    { value: "assist", label: t("communityAssist.assist") },
                  ]}
                  onChange={(value) => setMobilePane(String(value))}
                />
              </div>
            )}
            <div
              className={styles.composerLayout}
              data-assisting={assisting}
              data-mobile-pane={mobilePane}
              style={{ "--assist-width": `${assistWidth}%` } as CSSProperties}
            >
              <main className={styles.writingPane}>
                <div className={styles.composeIntro}>
                  <span>{t("communityAssist.composeIntro")}</span>
                  <span className={styles.hint}>
                    {t("communityCompose.account", {
                      name: status.account?.display_name,
                    })}
                  </span>
                </div>
                <section
                  className={styles.writingSection}
                  aria-label={t("communityAssist.postSetup")}
                >
                  <h2 className={styles.sectionHeading}>
                    <span className={styles.sectionNumber}>01</span>
                    {t("communityAssist.postSetup")}
                  </h2>
                  <Segmented
                    block
                    className={styles.typePicker}
                    aria-label={t("communityPage.type")}
                    value={type === "question" ? "question" : "article"}
                    disabled={locked}
                    options={[
                      {
                        value: "question",
                        label: (
                          <span className={styles.typeOption}>
                            <MessageCircleQuestion size={19} />
                            <span>
                              <strong>{t("communityPage.question")}</strong>
                              <small aria-hidden="true">
                                {t("communityAssist.questionShort")}
                              </small>
                            </span>
                          </span>
                        ),
                      },
                      {
                        value: "article",
                        label: (
                          <span className={styles.typeOption}>
                            <FileText size={19} />
                            <span>
                              <strong>{t("communityAssist.article")}</strong>
                              <small aria-hidden="true">
                                {t("communityAssist.articleShort")}
                              </small>
                            </span>
                          </span>
                        ),
                      },
                    ]}
                    onChange={(value) =>
                      changeType(
                        value === "question"
                          ? "question"
                          : articleBoard.current,
                      )
                    }
                  />
                  {type !== "question" && (
                    <div className={styles.boardRow}>
                      <label htmlFor="community-post-type">
                        {t("communityAssist.board")}
                      </label>
                      <Select
                        id="community-post-type"
                        style={{ minWidth: 220, maxWidth: "100%" }}
                        popupMatchSelectWidth={false}
                        dropdownStyle={{ maxWidth: "calc(100vw - 32px)" }}
                        optionRender={(option) => (
                          <span style={{ whiteSpace: "normal" }}>
                            {option.label}
                          </span>
                        )}
                        value={type}
                        onChange={changeType}
                        disabled={locked}
                        options={COMMUNITY_POST_TYPES.filter(
                          (value) => value !== "question",
                        ).map((value) => ({
                          value,
                          label: t(`communityPage.${value}`),
                        }))}
                      />
                    </div>
                  )}
                </section>
                <section
                  className={styles.writingSection}
                  aria-label={t("communityAssist.relatedResources")}
                >
                  <h2 className={styles.sectionHeading}>
                    <span className={styles.sectionNumber}>02</span>
                    {t("communityAssist.relatedResources")}
                  </h2>
                  <div className={styles.resourceSummary}>
                    <span
                      className={styles.resourceSummaryIcon}
                      aria-hidden="true"
                    >
                      <Link2 size={20} />
                    </span>
                    <div>
                      <strong>{t("communityAssist.linkContext")}</strong>
                      <p>{t("communityAssist.linkContextHelp")}</p>
                    </div>
                    <Button
                      className={styles.addResourcesButton}
                      icon={
                        addingResources ? (
                          <ChevronDown size={16} />
                        ) : (
                          <Plus size={16} />
                        )
                      }
                      disabled={locked}
                      loading={loadingResources}
                      aria-expanded={addingResources}
                      onClick={() =>
                        addingResources
                          ? setAddingResources(false)
                          : void loadResources()
                      }
                    >
                      {t(
                        addingResources
                          ? "communityAssist.collapseLinks"
                          : "communityAssist.addResources",
                      )}
                    </Button>
                  </div>
                  {resources.length > 0 && (
                    <div className={styles.resourceRow}>
                      {resources.map((item) => (
                        <Tag
                          key={reportResourceKey(item.origin)}
                          closable={
                            !locked &&
                            (!origin ||
                              reportResourceKey(item.origin) !==
                                reportResourceKey(origin))
                          }
                          onClose={() => {
                            setResources((current) =>
                              current.filter(
                                (resource) =>
                                  reportResourceKey(resource.origin) !==
                                  reportResourceKey(item.origin),
                              ),
                            );
                            setConfirmed(false);
                          }}
                        >
                          {item.name} · {item.origin.resource_type}
                        </Tag>
                      ))}
                    </div>
                  )}
                  {addingResources && (
                    <ResourcePicker
                      installed={catalog}
                      selected={resources}
                      disabled={locked}
                      onChange={(selected) => {
                        if (
                          origin &&
                          !selected.some(
                            (item) =>
                              communityResourceIdentity(item.origin) ===
                              communityResourceIdentity(origin),
                          )
                        )
                          selected.unshift(
                            resources.find(
                              (item) =>
                                communityResourceIdentity(item.origin) ===
                                communityResourceIdentity(origin),
                            )!,
                          );
                        if (
                          [true, false].some(
                            (skill) =>
                              selected.filter(
                                (item) =>
                                  (item.origin.resource_type === "skill") ===
                                  skill,
                              ).length > 3,
                          )
                        ) {
                          setError("communityAssist.tooManyResources");
                          return;
                        }
                        setResources(selected);
                        setConfirmed(false);
                      }}
                    />
                  )}
                </section>
                <section
                  className={`${styles.writingSection} ${styles.contentSection}`}
                  aria-label={t("communityAssist.postContent")}
                >
                  <h2 className={styles.sectionHeading}>
                    <span className={styles.sectionNumber}>03</span>
                    {t("communityAssist.postContent")}
                  </h2>
                  {!content.trim() && !assisting && (
                    <button
                      type="button"
                      className={styles.assistStart}
                      onClick={showAssistance}
                    >
                      <Sparkles size={18} />
                      <span>
                        <strong>{t("communityAssist.startWithAgent")}</strong>
                        <small>{t("communityAssist.startWithAgentHelp")}</small>
                      </span>
                    </button>
                  )}

                  <label htmlFor="community-post-title">
                    {t("communityCompose.postTitle")}
                  </label>
                  <Input
                    className={styles.titleInput}
                    placeholder={t("communityAssist.titlePlaceholder")}
                    id="community-post-title"
                    value={title}
                    maxLength={256}
                    disabled={locked}
                    onChange={(event) => {
                      setTitle(event.target.value);
                      setConfirmed(false);
                    }}
                  />
                  <div className={styles.editorActions}>
                    <label htmlFor="community-post-body">
                      {t("communityCompose.body")}
                    </label>
                    <Button
                      size="small"
                      type="text"
                      icon={preview ? <Pencil size={14} /> : <Eye size={14} />}
                      disabled={locked}
                      aria-pressed={preview}
                      onClick={() => setPreview(!preview)}
                    >
                      {t(
                        preview
                          ? "communityAssist.edit"
                          : "communityAssist.preview",
                      )}
                    </Button>
                    <Button
                      size="small"
                      icon={<Sparkles size={14} />}
                      className={styles.assistToggle}
                      aria-expanded={assisting}
                      disabled={locked}
                      onClick={() =>
                        assisting ? setAssisting(false) : showAssistance()
                      }
                    >
                      {t("communityAssist.assist")}
                    </Button>
                  </div>
                  {preview ? (
                    <div className={styles.preview}>
                      <ReactMarkdown
                        components={externalLinkMarkdownComponents}
                      >
                        {content || t("communityAssist.emptyPreview")}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <Input.TextArea
                      placeholder={t(
                        type === "question"
                          ? "communityAssist.questionPlaceholder"
                          : "communityAssist.articlePlaceholder",
                      )}
                      id="community-post-body"
                      value={content}
                      maxLength={65536}
                      className={styles.bodyInput}
                      autoSize={{ minRows: 9, maxRows: 16 }}
                      disabled={locked}
                      onChange={(event) => {
                        setContent(event.target.value);
                        setConfirmed(false);
                      }}
                    />
                  )}
                  <div className={styles.editorHint}>
                    <span>{t("communityAssist.editorHint")}</span>
                    <span>{content.length.toLocaleString()} / 65,536</span>
                  </div>
                </section>
              </main>
              {assisting && (
                <div
                  className={styles.resizeHandle}
                  role="separator"
                  tabIndex={0}
                  aria-label={t("communityAssist.resizePane")}
                  aria-orientation="vertical"
                  aria-valuemin={30}
                  aria-valuemax={55}
                  aria-valuenow={assistWidth}
                  title={t("communityAssist.resizePane")}
                  onDoubleClick={() => setAssistWidth(35)}
                  onPointerDown={(event) => {
                    if (event.button !== 0) return;
                    event.preventDefault();
                    event.currentTarget.focus();
                    event.currentTarget.setPointerCapture(event.pointerId);
                  }}
                  onPointerMove={(event) => {
                    if (!event.currentTarget.hasPointerCapture(event.pointerId))
                      return;
                    const bounds =
                      event.currentTarget.parentElement!.getBoundingClientRect();
                    setAssistWidth(
                      Math.round(
                        Math.max(
                          30,
                          Math.min(
                            55,
                            ((bounds.right - event.clientX) / bounds.width) *
                              100,
                          ),
                        ),
                      ),
                    );
                  }}
                  onPointerUp={(event) => {
                    if (event.currentTarget.hasPointerCapture(event.pointerId))
                      event.currentTarget.releasePointerCapture(
                        event.pointerId,
                      );
                  }}
                  onKeyDown={(event) => {
                    if (
                      !["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                        event.key,
                      )
                    )
                      return;
                    event.preventDefault();
                    setAssistWidth((width) =>
                      event.key === "Home"
                        ? 30
                        : event.key === "End"
                        ? 55
                        : Math.max(
                            30,
                            Math.min(
                              55,
                              width + (event.key === "ArrowLeft" ? 2 : -2),
                            ),
                          ),
                    );
                  }}
                />
              )}
              {assistInitialized && readyKey === currentKey && (
                <aside
                  hidden={!assisting}
                  className={styles.assistancePane}
                  aria-label={t("communityAssist.assist")}
                >
                  <PostAssistance
                    key={currentKey}
                    sessionState={assistantSession}
                    onSessionChange={onAssistantSession}
                    resources={resources.map(
                      (item) =>
                        catalog.find(
                          (entry) =>
                            reportResourceKey(entry.origin) ===
                            reportResourceKey(item.origin),
                        ) || item,
                    )}
                    screenshots={screenshots}
                    articleType={type}
                    draft={`${title ? `# ${title}\n\n` : ""}${content}`}
                    instructions={instructions}
                    onInstructions={setInstructions}
                    onInsertImage={async (image, index) => {
                      const result = await request<{
                        url: string;
                        media_id: string;
                      }>("/community/media", {
                        method: "POST",
                        body: JSON.stringify({
                          data_url: image,
                          account_id: status.account!.id,
                          reviewed: true,
                        }),
                      });
                      if (!mounted.current) return;
                      setMedia((current) => [...current, result]);
                      setContent((current) =>
                        `${current.trimEnd()}\n\n![${t(
                          "communityAssist.screenshotAlt",
                          { index: index + 1 },
                        )}](${result.url})\n`.trimStart(),
                      );
                      setConfirmed(false);
                    }}
                    onBusy={setAssistBusy}
                    onApply={(text) => {
                      // Only a leading H1 is the post title; keep all body headings.
                      const match = text.match(
                        /^\s*# [\t ]*(\S[^\r\n]*)(?:\r?\n|$)/,
                      );
                      const body = match
                        ? text.slice(match[0].length).trimStart()
                        : text;
                      if (match)
                        setTitle(
                          match[1]
                            .replace(/\s+#+\s*$/, "")
                            .trim()
                            .slice(0, 256),
                        );
                      // Keep explicitly inserted images even if the model omitted them.
                      const imageLinks =
                        content.match(/!\[[^\]]*\]\(https:\/\/[^\s)]+\)/g) ||
                        [];
                      const missing = imageLinks.filter(
                        (link) =>
                          !text.includes(link.match(/\((.+)\)/)?.[1] || link),
                      );
                      setContent([body, ...missing].join("\n\n"));
                      setMobilePane("write");
                      setConfirmed(false);
                      setPreview(false);
                      document.getElementById("community-post-title")?.focus();
                    }}
                  />
                </aside>
              )}
            </div>
          </>
        )}
      </div>
    </ComposerFrame>
  );
}
