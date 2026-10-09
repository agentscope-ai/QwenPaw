import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Avatar,
  Button,
  Empty,
  Image,
  Input,
  Pagination,
  Spin,
} from "antd";
import type { TextAreaRef } from "antd/es/input/TextArea";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CircleCheck, ThumbsUp } from "lucide-react";
import type { CommunityConnectionStatus } from "@/api/modules/community";
import { communityErrorKey } from "@/utils/communityError";
import { communityPostsApi, type Comment, type Page } from "./api";
import { CommunityAnchor } from "./PostBody";
import { mediaUrl } from "./media";
import { isCustomEmoji, markdownWithCustomEmoji } from "./customEmoji";
import styles from "./index.module.less";

function CommentThread({
  comment,
  onReply,
  accountId,
  question,
  acceptedIds,
}: {
  comment: Comment;
  onReply: (comment: Comment) => void;
  accountId?: string;
  question: boolean;
  acceptedIds: string[];
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [liked, setLiked] = useState(Boolean(comment.liked));
  const [count, setCount] = useState(comment.like_count || 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    setLiked(Boolean(comment.liked));
    setCount(comment.like_count || 0);
  }, [comment.liked, comment.like_count]);
  const vote = async () => {
    if (!accountId) {
      navigate("/settings/community");
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
  return (
    <div className={styles.comment}>
      <div className={styles.authorRow}>
        <Avatar size={30} src={mediaUrl(comment.author_avatar_url)}>
          {comment.author_name?.slice(0, 1)}
        </Avatar>
        <span className={styles.authorName}>{comment.author_name}</span>
        {(comment.accepted || acceptedIds.includes(comment.id)) && (
          <span className={styles.solvedStatus}>
            <CircleCheck size={14} aria-hidden="true" />
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
          {markdownWithCustomEmoji(comment.content)}
        </ReactMarkdown>
        {!!comment.image_urls?.length && (
          <div className={styles.commentImages}>
            <Image.PreviewGroup>
              {Array.from(new Set(comment.image_urls))
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
        )}
      </div>
      <div className={styles.commentActions}>
        <Button
          type="text"
          size="small"
          aria-pressed={liked}
          className={liked ? styles.activeAction : undefined}
          loading={busy}
          icon={<ThumbsUp size={14} aria-hidden="true" />}
          onClick={() => void vote()}
        >
          {t(question ? "communityPage.helpful" : "communityPage.like")}{" "}
          {count || ""}
        </Button>
        <Button type="text" size="small" onClick={() => onReply(comment)}>
          {t("communityPage.reply")}
        </Button>
        <time className={styles.meta}>{comment.created_at?.slice(0, 10)}</time>
      </div>
      {error && <Alert type="error" message={t(error)} />}
      {comment.replies?.map((reply) => (
        <CommentThread
          key={reply.id}
          comment={reply}
          onReply={onReply}
          accountId={accountId}
          question={question}
          acceptedIds={acceptedIds}
        />
      ))}
    </div>
  );
}

export function Discussion({
  id,
  kind,
  connection,
  acceptedIds = [],
  focusRequest = 0,
}: {
  id: string;
  kind?: "answer" | "comment";
  connection?: CommunityConnectionStatus;
  acceptedIds?: string[];
  focusRequest?: number;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [comments, setComments] = useState<Page<Comment>>({
    items: [],
    total: 0,
  });
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [sendError, setSendError] = useState<string>();
  const [sending, setSending] = useState(false);
  const [draft, setDraft] = useState("");
  const [reply, setReply] = useState<Comment>();
  const editor = useRef<TextAreaRef>(null);
  const section = useRef<HTMLElement>(null);
  const accountId =
    connection?.status === "connected" ? connection.account?.id : undefined;
  const isAnswer = kind === "answer" && !reply;
  useEffect(() => {
    if (!focusRequest) return;
    section.current?.scrollIntoView?.({ block: "start" });
    editor.current?.focus();
  }, [focusRequest]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    communityPostsApi
      .comments(id, page, controller.signal, kind)
      .then((result) => {
        if (!controller.signal.aborted) setComments(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(communityErrorKey(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [id, page, reload, kind]);
  const send = async () => {
    if (!draft.trim() || !accountId || sending) return;
    setSending(true);
    setSendError(undefined);
    try {
      if (isAnswer)
        await communityPostsApi.comment(
          id,
          draft.trim(),
          accountId,
          undefined,
          "answer",
        );
      else
        await communityPostsApi.comment(id, draft.trim(), accountId, reply?.id);
      setDraft("");
      setReply(undefined);
      setPage(1);
      setReload((value) => value + 1);
    } catch (err) {
      setSendError(communityErrorKey(err));
    } finally {
      setSending(false);
    }
  };
  return (
    <section
      ref={section}
      className={styles.discussion}
      aria-label={t(
        kind === "answer" ? "communityPage.answers" : "communityPage.comments",
      )}
    >
      <h2>
        {t(
          kind === "answer"
            ? "communityPage.answers"
            : "communityPage.comments",
        )}{" "}
        <span className={styles.sectionCount}>{comments.total}</span>
      </h2>
      {accountId ? (
        <div className={styles.composer}>
          {reply && (
            <div>
              {t("communityPage.replyTo", { name: reply.author_name })}{" "}
              <Button type="text" onClick={() => setReply(undefined)}>
                {t("communityPage.cancelReply")}
              </Button>
            </div>
          )}
          <label htmlFor={`community-comment-${kind || "article"}`}>
            {t(
              isAnswer
                ? "communityPage.writeAnswer"
                : "communityPage.writeComment",
            )}
          </label>
          <Input.TextArea
            ref={editor}
            id={`community-comment-${kind || "article"}`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            autoSize={{ minRows: isAnswer ? 5 : 3, maxRows: 14 }}
            maxLength={65536}
            disabled={sending}
            placeholder={isAnswer ? t("communityPage.answerHint") : undefined}
          />
          {sendError && (
            <Alert
              type="error"
              message={t("communityPage.sendError")}
              description={t(sendError)}
            />
          )}
          <Button
            type="primary"
            loading={sending}
            disabled={!draft.trim()}
            onClick={() => void send()}
          >
            {t(isAnswer ? "communityPage.sendAnswer" : "communityPage.send")}
          </Button>
        </div>
      ) : (
        <div className={styles.loginHint}>
          <Link to="/settings/community">{t("communityPage.connect")}</Link>
        </div>
      )}
      {error && (
        <Alert
          type="error"
          message={t(error)}
          action={
            <Button onClick={() => setReload((v) => v + 1)}>
              {t("communityPage.retry")}
            </Button>
          }
        />
      )}
      <Spin spinning={loading}>
        {!loading && !error && !comments.items.length && (
          <Empty
            description={t(
              kind === "answer"
                ? "communityPage.noAnswers"
                : "communityPage.noComments",
            )}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        )}
        {comments.items.map((comment) => (
          <CommentThread
            key={comment.id}
            comment={comment}
            accountId={accountId}
            question={!!kind}
            acceptedIds={acceptedIds}
            onReply={(value) => {
              if (!accountId) {
                navigate("/settings/community");
                return;
              }
              setReply(value);
              section.current?.scrollIntoView?.({ block: "start" });
              editor.current?.focus();
            }}
          />
        ))}
      </Spin>
      {comments.total > 20 && (
        <Pagination
          current={page}
          pageSize={20}
          total={comments.total}
          showSizeChanger={false}
          onChange={setPage}
        />
      )}
    </section>
  );
}
