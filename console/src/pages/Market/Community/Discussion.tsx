import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, App, Avatar, Button, Empty, Image, Input, Spin } from "antd";
import type { TextAreaRef } from "antd/es/input/TextArea";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThumbsUp } from "lucide-react";
import { SparkThumbsUpFill, SparkThumbsUpLine } from "@agentscope-ai/icons";
import type { CommunityConnectionStatus } from "@/api/modules/community";
import { communityErrorKey } from "@/utils/communityError";
import { communityPostsApi, type Comment } from "./api";
import AuthorBadges from "./AuthorBadges";
import CommentEmojiPicker from "./CommentEmojiPicker";
import CommentImageAttachments, {
  commentMediaIds,
  type CommentImageAttachment,
} from "./CommentImageAttachments";
import MarkdownComposer, {
  type MarkdownComposerHandle,
} from "./MarkdownComposer";
import { CommunityAnchor } from "./PostBody";
import { mediaUrl } from "./media";
import { isCustomEmoji, markdownWithCustomEmoji } from "./customEmoji";
import styles from "./index.module.less";

/** Mirrors agentscope-platform-front: descendants collapse into one level. */
function flattenDescendants(nodes: Comment[] | undefined): Comment[] {
  if (!nodes?.length) return [];
  const result: Comment[] = [];
  const walk = (list: Comment[]) => {
    for (const node of list) {
      result.push(node);
      if (node.replies?.length) walk(node.replies);
    }
  };
  walk(nodes);
  return result;
}

function dedupeComments(items: Comment[]) {
  return items.filter(
    (item, index, all) =>
      all.findIndex((other) => other.id === item.id) === index,
  );
}

function upsertReply(
  nodes: Comment[],
  parentId: string,
  reply: Comment,
): Comment[] {
  return nodes.map((node) => {
    if (node.id === parentId)
      return { ...node, replies: [...(node.replies || []), reply] };
    if (!node.replies?.length) return node;
    return { ...node, replies: upsertReply(node.replies, parentId, reply) };
  });
}

/** Historical replies embed "@name " at the start; the badge shows it instead. */
function stripLeadingReplyMention(content: string, replyToName: string) {
  if (!replyToName) return content;
  const prefix = `@${replyToName}`;
  if (!content.startsWith(prefix)) return content;
  const rest = content.slice(prefix.length);
  if (rest.startsWith(" ")) return rest.slice(1);
  if (rest.startsWith("\n")) return rest;
  return content;
}

/** Plain-text comment body: @mentions in accent colour, emoji on their own row. */
function CommentBody({
  content,
  replyToName,
}: {
  content: string;
  replyToName?: string;
}) {
  const name = replyToName?.trim() || "";
  const text = stripLeadingReplyMention(content, name);
  const parts = text.split(/(@[^\s@]+|\[emoji:[^\]\n]+\])/g);
  const nodes: React.ReactNode[] = [];
  let emojiRow: React.ReactNode[] = [];
  const flushEmojiRow = () => {
    if (!emojiRow.length) return;
    nodes.push(
      <span key={`emoji-row-${nodes.length}`} className={styles.emojiRow}>
        {emojiRow}
      </span>,
    );
    emojiRow = [];
  };
  parts.forEach((part, index) => {
    if (part.startsWith("@")) {
      flushEmojiRow();
      nodes.push(
        <span key={index} className={styles.mention}>
          {part}
        </span>,
      );
      return;
    }
    const emoji = /^\[emoji:([^\]\n]+)\]$/.exec(part);
    if (emoji && isCustomEmoji(emoji[1])) {
      emojiRow.push(
        <img
          key={index}
          src={emoji[1]}
          alt="emoji"
          className={styles.customEmoji}
          loading="lazy"
          referrerPolicy="no-referrer"
        />,
      );
      return;
    }
    if (!part) return;
    flushEmojiRow();
    nodes.push(<span key={index}>{part}</span>);
  });
  flushEmojiRow();
  return (
    <span>
      {name && <span className={styles.mention}>{`@${name} `}</span>}
      {nodes}
    </span>
  );
}

function CommentImages({ urls }: { urls?: string[] }) {
  const { t } = useTranslation();
  if (!urls?.length) return null;
  return (
    <div className={styles.commentImages}>
      <Image.PreviewGroup>
        {Array.from(new Set(urls))
          .filter((url) => /^https?:\/\//i.test(url))
          .map((url, index) => (
            <Image
              key={url}
              src={url}
              alt={t("communityPage.commentImage", { number: index + 1 })}
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          ))}
      </Image.PreviewGroup>
    </div>
  );
}

function LoadMoreSentinel({ onVisible }: { onVisible: () => void }) {
  const nodeRef = useRef<HTMLDivElement | null>(null);
  const callbackRef = useRef(onVisible);
  callbackRef.current = onVisible;
  useEffect(() => {
    const node = nodeRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting))
          callbackRef.current();
      },
      { rootMargin: "120px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return <div ref={nodeRef} className={styles.sentinel} />;
}

function LoadMoreRow({
  hasMore,
  blocked,
  resetKey,
  onLoadMore,
}: {
  hasMore: boolean;
  blocked: boolean;
  resetKey: number;
  onLoadMore: () => void;
}) {
  const { t } = useTranslation();
  if (!hasMore) return null;
  return (
    <div className={styles.loadMoreRow}>
      {blocked ? (
        <Button onClick={onLoadMore}>{t("market.loadMore")}</Button>
      ) : (
        <LoadMoreSentinel key={resetKey} onVisible={onLoadMore} />
      )}
    </div>
  );
}

interface CommentListState {
  items: Comment[];
  setItems: React.Dispatch<React.SetStateAction<Comment[]>>;
  total: number;
  setTotal: React.Dispatch<React.SetStateAction<number>>;
  loading: boolean;
  loadingMore: boolean;
  blocked: boolean;
  error?: string;
  loadMore: () => void;
  retry: () => void;
}

function useCommentList(
  id: string,
  kind?: "answer" | "comment",
): CommentListState {
  const [items, setItems] = useState<Comment[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState<string>();
  const [reload, setReload] = useState(0);
  const pageRef = useRef(1);
  const busyRef = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    communityPostsApi
      .comments(id, 1, controller.signal, kind)
      .then((result) => {
        if (controller.signal.aborted) return;
        setItems(dedupeComments(result.items));
        setTotal(result.total);
        pageRef.current = 1;
        setBlocked(false);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(communityErrorKey(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [id, kind, reload]);
  const loadMore = useCallback(() => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoadingMore(true);
    const next = pageRef.current + 1;
    communityPostsApi
      .comments(id, next, undefined, kind)
      .then((result) => {
        setItems((prev) => dedupeComments([...prev, ...result.items]));
        setTotal(result.total);
        pageRef.current = next;
        setBlocked(false);
      })
      .catch(() => setBlocked(true))
      .finally(() => {
        busyRef.current = false;
        setLoadingMore(false);
      });
  }, [id, kind]);
  return {
    items,
    setItems,
    total,
    setTotal,
    loading,
    loadingMore,
    blocked,
    error,
    loadMore,
    retry: () => setReload((value) => value + 1),
  };
}

function CommentRow({
  comment,
  postId,
  accountId,
  isReply = false,
  onReplied,
  onRequireLogin,
}: {
  comment: Comment;
  postId: string;
  accountId?: string;
  isReply?: boolean;
  onReplied: (parentId: string, reply: Comment) => void;
  onRequireLogin: () => void;
}) {
  const { t } = useTranslation();
  const [liked, setLiked] = useState(Boolean(comment.liked));
  const [count, setCount] = useState(comment.like_count || 0);
  const [busy, setBusy] = useState(false);
  const [replyOpen, setReplyOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const [images, setImages] = useState<CommentImageAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const replyEditor = useRef<TextAreaRef>(null);
  useEffect(() => {
    setLiked(Boolean(comment.liked));
    setCount(comment.like_count || 0);
  }, [comment.liked, comment.like_count]);
  const vote = async () => {
    if (!accountId) {
      onRequireLogin();
      return;
    }
    if (busy) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await communityPostsApi.likeComment(comment.id, accountId);
      const next = result.liked ?? !liked;
      setCount(
        result.like_count ??
          Math.max(0, count + (next === liked ? 0 : next ? 1 : -1)),
      );
      setLiked(next);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setBusy(false);
    }
  };
  const submitReply = async () => {
    if (!accountId) {
      onRequireLogin();
      return;
    }
    if (!draft.trim() || sending || uploading) return;
    setSending(true);
    setError(undefined);
    try {
      const created = await communityPostsApi.comment(
        postId,
        draft.trim(),
        accountId,
        comment.id,
        "comment",
        commentMediaIds(images),
      );
      onReplied(comment.id, created);
      setDraft("");
      setImages([]);
      setReplyOpen(false);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setSending(false);
    }
  };
  return (
    <div className={isReply ? styles.replyItem : styles.commentItem}>
      <div className={styles.commentRow}>
        <Avatar
          size={isReply ? 28 : 32}
          src={mediaUrl(comment.author_avatar_url)}
        >
          {comment.author_name?.slice(0, 1)}
        </Avatar>
        <div className={styles.commentMain}>
          <p className={styles.commentLine}>
            <span className={styles.commentAuthor}>
              {comment.author_name}
              <AuthorBadges
                identity_badge={comment.identity_badge}
                identity_badges={comment.identity_badges}
              />
            </span>
            <CommentBody
              content={comment.content}
              replyToName={comment.reply_to_user_display_name}
            />
          </p>
          <CommentImages urls={comment.image_urls} />
          <div className={styles.commentMeta}>
            <time className={styles.meta}>
              {comment.created_at?.slice(0, 10)}
            </time>
            <button
              type="button"
              className={`${styles.likeBtn} ${
                liked ? styles.likeBtnActive : ""
              }`}
              aria-label={t("communityPage.like")}
              aria-pressed={liked}
              disabled={busy}
              onClick={() => void vote()}
            >
              <ThumbsUp size={14} aria-hidden="true" />
              {count || ""}
            </button>
            <button
              type="button"
              className={styles.likeBtn}
              onClick={() => {
                setReplyOpen((value) => !value);
                setError(undefined);
              }}
            >
              {t("communityPage.reply")}
            </button>
          </div>
          {error && <Alert type="error" message={t(error)} />}
          {replyOpen && (
            <div className={styles.inlineComposer}>
              <Input.TextArea
                ref={replyEditor}
                aria-label={t("communityPage.replyTo", {
                  name: comment.author_name,
                })}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                autoSize={{ minRows: 2, maxRows: 8 }}
                maxLength={65536}
                placeholder={t("communityPage.commentPlaceholder")}
                disabled={sending}
                variant="borderless"
              />
              <div className={styles.composerFooter}>
                <div className={styles.composerTools}>
                  {accountId ? (
                    <>
                      <CommentEmojiPicker
                        getEditor={() =>
                          replyEditor.current?.resizableTextArea?.textArea ??
                          null
                        }
                        onChange={setDraft}
                        disabled={sending || uploading}
                      />
                      <CommentImageAttachments
                        accountId={accountId}
                        value={images}
                        onChange={setImages}
                        onUploadingChange={setUploading}
                        disabled={sending}
                      />
                    </>
                  ) : null}
                </div>
                <div className={styles.composerActions}>
                  <Button
                    size="small"
                    onClick={() => {
                      setReplyOpen(false);
                      setDraft("");
                      setImages([]);
                      setError(undefined);
                    }}
                  >
                    {t("communityPage.cancelReply")}
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    loading={sending}
                    disabled={!draft.trim() || uploading}
                    onClick={() => void submitReply()}
                  >
                    {t("communityPage.sendReply")}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      {!isReply && !!comment.replies?.length && (
        <div className={styles.replyList}>
          {flattenDescendants(comment.replies).map((reply) => (
            <CommentRow
              key={reply.id}
              comment={reply}
              postId={postId}
              accountId={accountId}
              isReply
              onReplied={onReplied}
              onRequireLogin={onRequireLogin}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ThreadList({
  items,
  postId,
  accountId,
  onReplied,
  onRequireLogin,
}: {
  items: Comment[];
  postId: string;
  accountId?: string;
  onReplied: (parentId: string, reply: Comment) => void;
  onRequireLogin: () => void;
}) {
  return (
    <div className={styles.threadList}>
      {items.map((comment) => (
        <CommentRow
          key={comment.id}
          comment={comment}
          postId={postId}
          accountId={accountId}
          onReplied={onReplied}
          onRequireLogin={onRequireLogin}
        />
      ))}
    </div>
  );
}

function LoginHint() {
  const { t } = useTranslation();
  return (
    <div className={styles.loginHint}>
      <Link to="/settings/community">{t("communityPage.connect")}</Link>
    </div>
  );
}

function accountOf(connection?: CommunityConnectionStatus) {
  return connection?.status === "connected"
    ? connection.account?.id
    : undefined;
}

/** Article detail: title + always-on composer + flat comment list. */
export function ArticleComments({
  id,
  connection,
  focusRequest = 0,
}: {
  id: string;
  connection?: CommunityConnectionStatus;
  focusRequest?: number;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const list = useCommentList(id);
  const accountId = accountOf(connection);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const [images, setImages] = useState<CommentImageAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const editor = useRef<TextAreaRef>(null);
  useEffect(() => {
    if (!focusRequest) return;
    editor.current?.focus();
  }, [focusRequest]);
  const submit = async () => {
    if (!accountId || !draft.trim() || sending || uploading) return;
    setSending(true);
    setError(undefined);
    try {
      const created = await communityPostsApi.comment(
        id,
        draft.trim(),
        accountId,
        undefined,
        "comment",
        commentMediaIds(images),
      );
      list.setItems((prev) => [created, ...prev]);
      list.setTotal((prev) => prev + 1);
      setDraft("");
      setImages([]);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setSending(false);
    }
  };
  const onReplied = (parentId: string, reply: Comment) => {
    list.setItems((prev) => upsertReply(prev, parentId, reply));
    list.setTotal((prev) => prev + 1);
  };
  return (
    <section
      className={styles.discussion}
      aria-label={t("communityPage.comments")}
    >
      <h2 className={styles.discussionTitle}>
        {t("communityPage.comments")}
        <span className={styles.sectionCount}>{list.total}</span>
      </h2>
      {accountId ? (
        <div className={styles.composerBox}>
          <Input.TextArea
            ref={editor}
            aria-label={t("communityPage.writeComment")}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            autoSize={{ minRows: 3, maxRows: 12 }}
            maxLength={65536}
            placeholder={t("communityPage.commentPlaceholder")}
            disabled={sending}
            variant="borderless"
          />
          {error && (
            <Alert
              type="error"
              message={t("communityPage.sendError")}
              description={t(error)}
            />
          )}
          <div className={styles.composerFooter}>
            <div className={styles.composerTools}>
              <CommentEmojiPicker
                getEditor={() =>
                  editor.current?.resizableTextArea?.textArea ?? null
                }
                onChange={setDraft}
                disabled={sending || uploading}
              />
              <CommentImageAttachments
                accountId={accountId}
                value={images}
                onChange={setImages}
                onUploadingChange={setUploading}
                disabled={sending}
              />
            </div>
            <div className={styles.composerActions}>
              <Button
                type="primary"
                loading={sending}
                disabled={!draft.trim() || uploading}
                onClick={() => void submit()}
              >
                {t("communityPage.send")}
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <LoginHint />
      )}
      {list.loading ? (
        <div className={styles.threadSpin}>
          <Spin />
        </div>
      ) : list.error ? (
        <Alert
          type="error"
          message={t(list.error)}
          action={
            <Button onClick={list.retry}>{t("communityPage.retry")}</Button>
          }
        />
      ) : !list.items.length ? (
        <Empty
          description={t("communityPage.noComments")}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <ThreadList
          items={list.items}
          postId={id}
          accountId={accountId}
          onReplied={onReplied}
          onRequireLogin={() => navigate("/settings/community")}
        />
      )}
      <LoadMoreRow
        hasMore={list.items.length < list.total}
        blocked={list.blocked}
        resetKey={list.items.length}
        onLoadMore={list.loadMore}
      />
    </section>
  );
}

/** Question detail: comment thread embedded at the bottom of the question card. */
export function QuestionComments({
  id,
  connection,
  composeRequest = 0,
}: {
  id: string;
  connection?: CommunityConnectionStatus;
  composeRequest?: number;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const list = useCommentList(id, "comment");
  const accountId = accountOf(connection);
  const [composeOpen, setComposeOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const [images, setImages] = useState<CommentImageAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const section = useRef<HTMLDivElement>(null);
  const editor = useRef<TextAreaRef>(null);
  useEffect(() => {
    if (!composeRequest) return;
    setComposeOpen(true);
    section.current?.scrollIntoView?.({ block: "nearest" });
    editor.current?.focus();
  }, [composeRequest]);
  const submit = async () => {
    if (!accountId || !draft.trim() || sending || uploading) return;
    setSending(true);
    setError(undefined);
    try {
      const created = await communityPostsApi.comment(
        id,
        draft.trim(),
        accountId,
        undefined,
        "comment",
        commentMediaIds(images),
      );
      list.setItems((prev) => [created, ...prev]);
      list.setTotal((prev) => prev + 1);
      setDraft("");
      setImages([]);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setSending(false);
    }
  };
  const onReplied = (parentId: string, reply: Comment) => {
    list.setItems((prev) => upsertReply(prev, parentId, reply));
    list.setTotal((prev) => prev + 1);
  };
  return (
    <div className={styles.questionThread} ref={section}>
      {composeOpen &&
        (accountId ? (
          <div className={styles.inlineComposer}>
            <Input.TextArea
              ref={editor}
              aria-label={t("communityPage.writeComment")}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              autoSize={{ minRows: 3, maxRows: 12 }}
              maxLength={65536}
              placeholder={t("communityPage.commentPlaceholder")}
              disabled={sending}
              variant="borderless"
            />
            {error && (
              <Alert
                type="error"
                message={t("communityPage.sendError")}
                description={t(error)}
              />
            )}
            <div className={styles.composerFooter}>
              <div className={styles.composerTools}>
                <CommentEmojiPicker
                  getEditor={() =>
                    editor.current?.resizableTextArea?.textArea ?? null
                  }
                  onChange={setDraft}
                  disabled={sending || uploading}
                />
                <CommentImageAttachments
                  accountId={accountId}
                  value={images}
                  onChange={setImages}
                  onUploadingChange={setUploading}
                  disabled={sending}
                />
              </div>
              <div className={styles.composerActions}>
                <Button
                  size="small"
                  onClick={() => {
                    setComposeOpen(false);
                    setDraft("");
                    setImages([]);
                    setError(undefined);
                  }}
                >
                  {t("communityPage.cancelReply")}
                </Button>
                <Button
                  size="small"
                  type="primary"
                  loading={sending}
                  disabled={!draft.trim() || uploading}
                  onClick={() => void submit()}
                >
                  {t("communityPage.send")}
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <LoginHint />
        ))}
      {list.loading ? (
        <div className={styles.threadSpin}>
          <Spin size="small" />
        </div>
      ) : list.error ? (
        <Alert
          type="error"
          message={t(list.error)}
          action={
            <Button onClick={list.retry}>{t("communityPage.retry")}</Button>
          }
        />
      ) : (
        <ThreadList
          items={list.items}
          postId={id}
          accountId={accountId}
          onReplied={onReplied}
          onRequireLogin={() => navigate("/settings/community")}
        />
      )}
      <LoadMoreRow
        hasMore={list.items.length < list.total}
        blocked={list.blocked}
        resetKey={list.items.length}
        onLoadMore={list.loadMore}
      />
    </div>
  );
}

function AnswerCard({
  postId,
  answer,
  accountId,
  isAuthor,
  acceptedIds,
  onAccepted,
  onReplied,
  onRequireLogin,
}: {
  postId: string;
  answer: Comment;
  accountId?: string;
  isAuthor: boolean;
  acceptedIds: string[];
  onAccepted: (detail: Partial<import("./api").Post>) => void;
  onReplied: (parentId: string, reply: Comment) => void;
  onRequireLogin: () => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [liked, setLiked] = useState(Boolean(answer.liked));
  const [count, setCount] = useState(answer.like_count || 0);
  const [busy, setBusy] = useState(false);
  const [acceptBusy, setAcceptBusy] = useState(false);
  const [acceptError, setAcceptError] = useState<string>();
  const [composeOpen, setComposeOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const [images, setImages] = useState<CommentImageAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const answerEditor = useRef<TextAreaRef>(null);
  useEffect(() => {
    setLiked(Boolean(answer.liked));
    setCount(answer.like_count || 0);
  }, [answer.liked, answer.like_count]);
  const accepted = Boolean(answer.accepted) || acceptedIds.includes(answer.id);
  const vote = async () => {
    if (!accountId) {
      onRequireLogin();
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      const result = await communityPostsApi.likeComment(answer.id, accountId);
      const next = result.liked ?? !liked;
      setCount(
        result.like_count ??
          Math.max(0, count + (next === liked ? 0 : next ? 1 : -1)),
      );
      setLiked(next);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setBusy(false);
    }
  };
  const toggleAccept = async () => {
    if (!accountId) {
      onRequireLogin();
      return;
    }
    setAcceptBusy(true);
    setAcceptError(undefined);
    try {
      const detail = accepted
        ? await communityPostsApi.unacceptComment(postId, answer.id, accountId)
        : await communityPostsApi.acceptComment(postId, answer.id, accountId);
      onAccepted(detail);
      message.success(
        t(
          accepted
            ? "communityPage.unacceptSuccess"
            : "communityPage.acceptSuccess",
        ),
      );
    } catch (err) {
      setAcceptError(communityErrorKey(err));
    } finally {
      setAcceptBusy(false);
    }
  };
  const submitComment = async () => {
    if (!accountId || !draft.trim() || sending || uploading) return;
    setSending(true);
    setError(undefined);
    try {
      const created = await communityPostsApi.comment(
        postId,
        draft.trim(),
        accountId,
        answer.id,
        "comment",
        commentMediaIds(images),
      );
      onReplied(answer.id, created);
      setDraft("");
      setImages([]);
      setComposeOpen(false);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setSending(false);
    }
  };
  return (
    <article className={styles.answerCard}>
      <div className={styles.answerHeader}>
        <Avatar size={40} src={mediaUrl(answer.author_avatar_url)}>
          {answer.author_name?.slice(0, 1)}
        </Avatar>
        <span className={styles.answerAuthor}>{answer.author_name}</span>
        <AuthorBadges
          identity_badge={answer.identity_badge}
          identity_badges={answer.identity_badges}
        />
        {accepted && (
          <span className={`${styles.answerBadge} ${styles.answerBadgeSolved}`}>
            {t("communityPage.acceptedAnswer")}
          </span>
        )}
      </div>
      <div className={styles.commentContent}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: CommunityAnchor,
            img: ({ src, alt }) => (
              <img
                src={mediaUrl(src)}
                alt={alt || ""}
                className={isCustomEmoji(src) ? styles.customEmoji : undefined}
                loading="lazy"
                referrerPolicy="no-referrer"
              />
            ),
          }}
        >
          {markdownWithCustomEmoji(answer.content)}
        </ReactMarkdown>
        <CommentImages urls={answer.image_urls} />
      </div>
      <div className={styles.answerMeta}>
        {isAuthor && (
          <Button
            className={styles.qaActionBtn}
            loading={acceptBusy}
            icon={
              accepted ? (
                <SparkThumbsUpFill size={14} aria-hidden="true" />
              ) : (
                <SparkThumbsUpLine size={14} aria-hidden="true" />
              )
            }
            onClick={() => void toggleAccept()}
          >
            {t(
              accepted
                ? "communityPage.acceptedAnswer"
                : "communityPage.acceptAnswer",
            )}
          </Button>
        )}
        <Button
          className={styles.qaActionBtn}
          aria-pressed={liked}
          loading={busy}
          icon={<ThumbsUp size={14} aria-hidden="true" />}
          onClick={() => void vote()}
        >
          {t("communityPage.helpful")} {count || ""}
        </Button>
        <Button
          type="text"
          size="small"
          onClick={() => setComposeOpen((v) => !v)}
        >
          {t("communityPage.commentAction")}
        </Button>
        <time className={styles.meta}>{answer.created_at?.slice(0, 10)}</time>
      </div>
      {acceptError && <Alert type="error" message={t(acceptError)} />}
      {(composeOpen || !!answer.replies?.length) && (
        <div className={styles.answerThread}>
          {composeOpen &&
            (accountId ? (
              <div className={styles.inlineComposer}>
                <Input.TextArea
                  ref={answerEditor}
                  aria-label={t("communityPage.writeComment")}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  autoSize={{ minRows: 2, maxRows: 8 }}
                  maxLength={65536}
                  placeholder={t("communityPage.commentPlaceholder")}
                  disabled={sending}
                  variant="borderless"
                />
                {error && <Alert type="error" message={t(error)} />}
                <div className={styles.composerFooter}>
                  <div className={styles.composerTools}>
                    <CommentEmojiPicker
                      getEditor={() =>
                        answerEditor.current?.resizableTextArea?.textArea ??
                        null
                      }
                      onChange={setDraft}
                      disabled={sending || uploading}
                    />
                    <CommentImageAttachments
                      accountId={accountId}
                      value={images}
                      onChange={setImages}
                      onUploadingChange={setUploading}
                      disabled={sending}
                    />
                  </div>
                  <div className={styles.composerActions}>
                    <Button
                      size="small"
                      onClick={() => {
                        setComposeOpen(false);
                        setDraft("");
                        setImages([]);
                        setError(undefined);
                      }}
                    >
                      {t("communityPage.cancelReply")}
                    </Button>
                    <Button
                      size="small"
                      type="primary"
                      loading={sending}
                      disabled={!draft.trim() || uploading}
                      onClick={() => void submitComment()}
                    >
                      {t("communityPage.send")}
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <LoginHint />
            ))}
          {!!answer.replies?.length && (
            <div className={styles.threadList}>
              {flattenDescendants(answer.replies).map((reply) => (
                <CommentRow
                  key={reply.id}
                  comment={reply}
                  postId={postId}
                  accountId={accountId}
                  isReply
                  onReplied={onReplied}
                  onRequireLogin={onRequireLogin}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

/** Question detail: answer composer card followed by one card per answer. */
export function AnswersSection({
  id,
  connection,
  isAuthor = false,
  acceptedIds = [],
  onAccepted,
  focusRequest = 0,
}: {
  id: string;
  connection?: CommunityConnectionStatus;
  isAuthor?: boolean;
  acceptedIds?: string[];
  onAccepted: (detail: Partial<import("./api").Post>) => void;
  focusRequest?: number;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const list = useCommentList(id, "answer");
  const accountId = accountOf(connection);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const [composeOpen, setComposeOpen] = useState(false);
  const card = useRef<HTMLDivElement>(null);
  const editor = useRef<MarkdownComposerHandle>(null);
  useEffect(() => {
    if (!focusRequest) return;
    setComposeOpen(true);
  }, [focusRequest]);
  useEffect(() => {
    if (!focusRequest || !composeOpen) return;
    card.current?.scrollIntoView?.({ block: "start" });
    // The composer may have just mounted; focus after the next paint.
    const raf = window.requestAnimationFrame(() => editor.current?.focus());
    return () => window.cancelAnimationFrame(raf);
  }, [focusRequest, composeOpen]);
  const submit = async () => {
    if (!accountId || !draft.trim() || sending) return;
    setSending(true);
    setError(undefined);
    try {
      const created = await communityPostsApi.comment(
        id,
        draft.trim(),
        accountId,
        undefined,
        "answer",
      );
      list.setItems((prev) => [...prev, created]);
      list.setTotal((prev) => prev + 1);
      setDraft("");
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setSending(false);
    }
  };
  const onReplied = (parentId: string, reply: Comment) => {
    list.setItems((prev) => upsertReply(prev, parentId, reply));
    list.setTotal((prev) => prev + 1);
  };
  const onRequireLogin = () => navigate("/settings/community");
  return (
    <section
      className={styles.answersSection}
      aria-label={t("communityPage.answers")}
    >
      {composeOpen && (
        <div className={styles.answerComposerCard} ref={card}>
          {accountId ? (
            <>
              <MarkdownComposer
                ref={editor}
                ariaLabel={t("communityPage.writeAnswer")}
                value={draft}
                onChange={setDraft}
                placeholder={t("communityPage.answerHint")}
                maxLength={65536}
                disabled={sending}
              />
              {error && (
                <Alert
                  type="error"
                  message={t("communityPage.sendError")}
                  description={t(error)}
                />
              )}
              <div className={styles.composerActions}>
                <Button
                  onClick={() => {
                    setComposeOpen(false);
                    setDraft("");
                    setError(undefined);
                  }}
                >
                  {t("common.cancel")}
                </Button>
                <Button
                  type="primary"
                  loading={sending}
                  disabled={!draft.trim()}
                  onClick={() => void submit()}
                >
                  {t("communityPage.sendAnswer")}
                </Button>
              </div>
            </>
          ) : (
            <LoginHint />
          )}
        </div>
      )}
      {list.loading ? (
        <div className={styles.threadSpin}>
          <Spin />
        </div>
      ) : list.error ? (
        <Alert
          type="error"
          message={t(list.error)}
          action={
            <Button onClick={list.retry}>{t("communityPage.retry")}</Button>
          }
        />
      ) : !list.items.length ? (
        <div className={styles.answerEmpty}>{t("communityPage.noAnswers")}</div>
      ) : (
        list.items.map((answer) => (
          <AnswerCard
            key={answer.id}
            postId={id}
            answer={answer}
            accountId={accountId}
            isAuthor={isAuthor}
            acceptedIds={acceptedIds}
            onAccepted={onAccepted}
            onReplied={onReplied}
            onRequireLogin={onRequireLogin}
          />
        ))
      )}
      <LoadMoreRow
        hasMore={list.items.length < list.total}
        blocked={list.blocked}
        resetKey={list.items.length}
        onLoadMore={list.loadMore}
      />
    </section>
  );
}
