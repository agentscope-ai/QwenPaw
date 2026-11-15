import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App, Avatar, Button, Spin } from "antd";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ExternalLink,
  Pencil,
  Trash2,
  MessageSquare,
  Share2,
  Star,
  ThumbsUp,
} from "lucide-react";
import { SparkThumbsUpFill, SparkVisableLine } from "@agentscope-ai/icons";
import {
  communityConnectionApi,
  type CommunityConnectionStatus,
} from "@/api/modules/community";
import { openExternalLink } from "@/utils/openExternalLink";
import { communityErrorKey } from "@/utils/communityError";
import { communityPostsApi, type Post } from "./api";
import AuthorBadges from "./AuthorBadges";
import { PostBody } from "./PostBody";
import { mediaUrl } from "./media";
import { EditPostModal } from "./EditPostModal";
import { ArticleToc } from "./ArticleTocCard";
import { RelatedResources } from "./RelatedResources";
import { extractHtmlToc, parseMarkdownToc } from "./articleToc";
import {
  ArticleComments,
  AnswersSection,
  QuestionComments,
} from "./Discussion";
import styles from "./index.module.less";

export function QuestionStatus({ post }: { post: Post }) {
  const { t } = useTranslation();
  if (post.article_type !== "question") return null;
  const count = Math.max(0, post.accepted_answer_count ?? 0);
  const solved = count > 0;
  return (
    <span
      className={`${styles.answerBadge} ${
        solved ? styles.answerBadgeSolved : styles.answerBadgeOpen
      }`}
    >
      {solved
        ? t("communityPage.solvedCount", { count })
        : t("communityPage.solveCount", { count })}
    </span>
  );
}
export function PostDetail({ id }: { id: string }) {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const backParams = new URLSearchParams(params);
  backParams.delete("post");
  const [post, setPost] = useState<Post>();
  const [connection, setConnection] = useState<CommunityConnectionStatus>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [actionError, setActionError] = useState<string>();
  const [busy, setBusy] = useState<"like" | "favorite" | "delete">();
  const [editing, setEditing] = useState(false);
  const [reload, setReload] = useState(0);
  const [focusRequest, setFocusRequest] = useState(0);
  const [answerRequest, setAnswerRequest] = useState(0);
  const barRef = useRef<HTMLDivElement>(null);
  const [barHidden, setBarHidden] = useState(false);
  const [barPinned, setBarPinned] = useState(false);
  const question = post?.article_type === "question";
  const tocItems = useMemo(
    () =>
      post?.body_html?.trim()
        ? extractHtmlToc(post.body_html)
        : parseMarkdownToc(post?.body_text || post?.summary || ""),
    [post],
  );
  // Mobile only: reading deeper (scroll down) fades the pinned interaction
  // bar away, scrolling back up brings it back; at its rested position or on
  // wide layouts the bar always stays visible.
  useEffect(() => {
    const node = barRef.current;
    if (!node) return;
    const media = window.matchMedia("(max-width: 600px)");
    let el: HTMLElement | null = node.parentElement;
    while (el) {
      const { overflowY } = getComputedStyle(el);
      if (overflowY === "auto" || overflowY === "scroll") break;
      el = el.parentElement;
    }
    const container = el;
    if (!container) return;
    // While the sticky bar floats at the scrollport bottom it gets the
    // rounded floating-card look; at its rested position the plain divider.
    const evaluate = () => {
      const pinned =
        node.getBoundingClientRect().bottom >=
        container.getBoundingClientRect().bottom - 14;
      setBarPinned(pinned);
      return pinned;
    };
    let last = container.scrollTop;
    const onScroll = () => {
      const top = container.scrollTop;
      const delta = top - last;
      if (Math.abs(delta) < 8) return;
      last = top;
      const pinned = evaluate();
      if (!media.matches) {
        setBarHidden(false);
        return;
      }
      setBarHidden(pinned && delta > 0);
    };
    const onBreak = () => {
      if (!media.matches) setBarHidden(false);
    };
    container.addEventListener("scroll", onScroll, { passive: true });
    media.addEventListener("change", onBreak);
    evaluate();
    return () => {
      container.removeEventListener("scroll", onScroll);
      media.removeEventListener("change", onBreak);
    };
  }, [post?.id]);
  const ownPost =
    connection?.status === "connected" &&
    !!connection.account?.id &&
    String(post?.author_user_id) === connection.account.id;
  const nativeEdit = !!post?.body_asl && !question;
  const removePost = () => {
    if (!ownPost || !connection?.account || busy) return;
    const accountId = connection.account.id;
    modal.confirm({
      title: t("communityPage.deleteTitle"),
      content: t("communityPage.deleteHelp", { title: post?.title }),
      okText: t("communityPage.deletePost"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        setBusy("delete");
        setActionError(undefined);
        try {
          await communityPostsApi.remove(id, accountId);
          message.success(t("communityPage.deleted"));
          navigate(`/market?${backParams}`, { replace: true });
        } catch (err) {
          setActionError(communityErrorKey(err));
          message.error(t(communityErrorKey(err)));
          throw err;
        } finally {
          setBusy(undefined);
        }
      },
    });
  };
  const platformUrl = `https://platform.agentscope.io/community/articles/${encodeURIComponent(
    id,
  )}`;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    Promise.all([
      communityPostsApi.detail(id, controller.signal),
      communityConnectionApi.status(controller.signal).catch(() => undefined),
    ])
      .then(([detail, status]) => {
        if (!controller.signal.aborted) {
          setPost(detail);
          setConnection(status);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(communityErrorKey(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [id, reload]);
  const interact = async (action: "like" | "favorite") => {
    if (connection?.status !== "connected" || !connection.account) {
      navigate("/settings/community");
      return;
    }
    if (busy || !post) return;
    setBusy(action);
    setActionError(undefined);
    try {
      const result = await communityPostsApi.interact(
        id,
        action,
        connection.account.id,
      );
      setPost((current) => {
        if (!current) return current;
        const state = action === "like" ? "liked" : "favorited";
        const count = action === "like" ? "like_count" : "favorite_count";
        const next = result[state] ?? !current[state];
        return {
          ...current,
          ...result,
          [state]: next,
          [count]:
            result[count] ??
            Math.max(
              0,
              (current[count] || 0) +
                (next === !!current[state] ? 0 : next ? 1 : -1),
            ),
        };
      });
    } catch (err) {
      setActionError(communityErrorKey(err));
    } finally {
      setBusy(undefined);
    }
  };
  const focusDiscussion = (target: "answer" | "comment") => {
    if (target === "answer") setAnswerRequest((v) => v + 1);
    else setFocusRequest((v) => v + 1);
  };
  const applyAccepted = (detail: Partial<Post>) =>
    setPost((prev) =>
      prev
        ? {
            ...prev,
            accepted_comment_ids:
              detail.accepted_comment_ids ?? prev.accepted_comment_ids,
            accepted_comment_id:
              detail.accepted_comment_id ?? prev.accepted_comment_id,
            accepted_answer_count:
              detail.accepted_answer_count ?? prev.accepted_answer_count,
            qa_status: detail.qa_status ?? prev.qa_status,
          }
        : prev,
    );
  const share = async () => {
    try {
      await navigator.clipboard.writeText(platformUrl);
      message.success(t("communityPage.linkCopied"));
    } catch {
      setActionError("communityPage.copyFailed");
    }
  };
  return (
    <>
      <div className={styles.detailHeader}>
        <Link className={styles.backLink} to={`/market?${backParams}`}>
          <ArrowLeft size={16} aria-hidden="true" />
          {t("communityPage.back")}
        </Link>
        {post && <div className={styles.detailHeaderTitle}>{post.title}</div>}
      </div>
      <div className={styles.content}>
        {error && (
          <Alert
            type="error"
            message={t(error)}
            description={t("communityPage.loadErrorHelp")}
            action={
              <Button onClick={() => setReload((v) => v + 1)}>
                {t("communityPage.retry")}
              </Button>
            }
          />
        )}
        {editing && post && connection?.account && (
          <EditPostModal
            post={post}
            accountId={connection.account.id}
            onClose={() => setEditing(false)}
            onSaved={() => {
              setEditing(false);
              setReload((v) => v + 1);
            }}
          />
        )}
        <Spin spinning={loading && Boolean(post)} size="large">
          {loading && !post && (
            <div className={styles.spinFill}>
              <Spin size="large" />
            </div>
          )}
          {post && (
            <div
              className={`${styles.detailLayout} ${
                tocItems.length ? "" : styles.detailLayoutNoToc
              }`}
            >
              <div className={styles.detailMain}>
                <article className={styles.articleCard}>
                  <div className={styles.articleTagRow}>
                    <span className={styles.postTag}>
                      {post.article_type_label ||
                        t(
                          question
                            ? "communityPage.question"
                            : "communityPage.article",
                        )}
                    </span>
                    {(post.tags || []).map((tag) => (
                      <span key={tag} className={styles.postTag}>
                        {tag}
                      </span>
                    ))}
                    <QuestionStatus post={post} />
                  </div>
                  <h1 className={styles.articleTitle}>{post.title}</h1>
                  <div className={styles.authorRow}>
                    <Avatar size={32} src={mediaUrl(post.author_avatar_url)}>
                      {post.author_name?.slice(0, 1)}
                    </Avatar>
                    <span className={styles.authorName}>
                      {post.author_name}
                    </span>
                    <AuthorBadges
                      officialIconOnly
                      identity_badge={post.identity_badge}
                      identity_badges={post.identity_badges}
                    />
                    <time className={styles.meta}>
                      {post.published_at?.slice(0, 10)}
                    </time>
                    {typeof post.view_count === "number" && (
                      <span className={`${styles.meta} ${styles.viewCount}`}>
                        <SparkVisableLine size={14} />
                        {post.view_count}
                      </span>
                    )}
                  </div>
                  {ownPost && (
                    <div className={styles.ownerActions}>
                      <Button
                        size="small"
                        icon={<Pencil size={14} />}
                        disabled={!!busy}
                        title={
                          nativeEdit ? t("communityPage.editHelp") : undefined
                        }
                        onClick={() => {
                          if (nativeEdit)
                            openExternalLink(
                              `https://platform.agentscope.io/community/write?articleId=${encodeURIComponent(
                                id,
                              )}`,
                            );
                          else setEditing(true);
                        }}
                      >
                        {t("communityPage.editPost")}
                        {nativeEdit && <ExternalLink size={12} />}
                      </Button>
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<Trash2 size={14} />}
                        disabled={!!busy}
                        loading={busy === "delete"}
                        onClick={removePost}
                      >
                        {t("communityPage.deletePost")}
                      </Button>
                      {nativeEdit && (
                        <span className={styles.meta}>
                          {t("communityPage.editHelp")}
                        </span>
                      )}
                    </div>
                  )}
                  <RelatedResources
                    skillIds={post.related_skill_ids}
                    pluginIds={post.related_plugin_ids}
                  />
                  <div>
                    <PostBody post={post} />
                    {question && (
                      <div className={styles.questionActionBar}>
                        <button
                          type="button"
                          className={styles.writeAnswerBtn}
                          onClick={() => focusDiscussion("answer")}
                        >
                          {t("communityPage.writeAnswer")}
                        </button>
                        <button
                          type="button"
                          className={styles.helpfulChip}
                          aria-pressed={!!post.liked}
                          disabled={!!busy}
                          onClick={() => void interact("like")}
                        >
                          {post.liked ? (
                            <SparkThumbsUpFill size={14} aria-hidden="true" />
                          ) : (
                            <ThumbsUp size={14} aria-hidden="true" />
                          )}
                          {t("communityPage.helpful")}
                          {post.like_count ? (
                            <>
                              {" "}
                              <span className={styles.barCount}>
                                {post.like_count}
                              </span>
                            </>
                          ) : null}
                        </button>
                        <button
                          type="button"
                          className={styles.plainAction}
                          onClick={() => focusDiscussion("comment")}
                        >
                          {t("communityPage.commentQuestion")}
                        </button>
                        <button
                          type="button"
                          className={styles.plainAction}
                          onClick={() => void share()}
                        >
                          <Share2 size={14} aria-hidden="true" />
                          {t("communityPage.share")}
                        </button>
                      </div>
                    )}
                    {actionError && (
                      <Alert type="error" message={t(actionError)} />
                    )}
                    {!question && (
                      <div
                        ref={barRef}
                        className={`${styles.bottomBar} ${
                          barPinned ? styles.bottomBarPinned : ""
                        } ${barHidden ? styles.bottomBarHidden : ""}`}
                      >
                        <button
                          type="button"
                          className={`${styles.barAction} ${
                            post.liked ? styles.barActionActive : ""
                          }`}
                          aria-pressed={!!post.liked}
                          disabled={!!busy}
                          onClick={() => void interact("like")}
                        >
                          {post.liked ? (
                            <SparkThumbsUpFill size={18} aria-hidden="true" />
                          ) : (
                            <ThumbsUp size={18} aria-hidden="true" />
                          )}
                          <span>
                            {t(
                              question
                                ? "communityPage.helpful"
                                : "communityPage.like",
                            )}
                          </span>{" "}
                          {post.like_count ? (
                            <span className={styles.barCount}>
                              {post.like_count}
                            </span>
                          ) : null}
                        </button>
                        {!question && (
                          <button
                            type="button"
                            className={`${styles.barAction} ${
                              post.favorited ? styles.barActionActive : ""
                            }`}
                            aria-pressed={!!post.favorited}
                            disabled={!!busy}
                            onClick={() => void interact("favorite")}
                          >
                            <Star
                              size={18}
                              fill={post.favorited ? "currentColor" : "none"}
                              aria-hidden="true"
                            />
                            <span>
                              {t(
                                post.favorited
                                  ? "communityPage.favorited"
                                  : "communityPage.favorite",
                              )}
                            </span>{" "}
                            {post.favorite_count ? (
                              <span className={styles.barCount}>
                                {post.favorite_count}
                              </span>
                            ) : null}
                          </button>
                        )}
                        <button
                          type="button"
                          className={styles.barAction}
                          onClick={() => focusDiscussion("comment")}
                        >
                          <MessageSquare size={18} aria-hidden="true" />
                          <span>
                            {t(
                              question
                                ? "communityPage.commentQuestion"
                                : "communityPage.comments",
                            )}
                          </span>{" "}
                          {post.comment_count ? (
                            <span className={styles.barCount}>
                              {post.comment_count}
                            </span>
                          ) : null}
                        </button>
                        <button
                          type="button"
                          className={styles.barAction}
                          onClick={() => void share()}
                        >
                          <Share2 size={18} aria-hidden="true" />
                          <span>{t("communityPage.share")}</span>
                        </button>
                      </div>
                    )}
                  </div>
                  {question && (
                    <QuestionComments
                      id={id}
                      connection={connection}
                      composeRequest={focusRequest}
                    />
                  )}
                </article>
                {question ? (
                  <AnswersSection
                    id={id}
                    connection={connection}
                    isAuthor={ownPost}
                    acceptedIds={
                      post.accepted_comment_ids ||
                      (post.accepted_comment_id
                        ? [post.accepted_comment_id]
                        : [])
                    }
                    onAccepted={applyAccepted}
                    focusRequest={answerRequest}
                  />
                ) : (
                  <div className={styles.discussionCard}>
                    <ArticleComments
                      id={id}
                      connection={connection}
                      focusRequest={focusRequest}
                    />
                  </div>
                )}
              </div>
              {tocItems.length > 0 && (
                <aside className={styles.detailSide}>
                  <ArticleToc items={tocItems} />
                </aside>
              )}
            </div>
          )}
        </Spin>
      </div>
    </>
  );
}
