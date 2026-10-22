import { useEffect, useState } from "react";
import { Alert, App, Avatar, Button, Segmented, Spin } from "antd";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Bookmark,
  CircleCheck,
  ExternalLink,
  Flag,
  Pencil,
  Trash2,
  MessageSquare,
  Share2,
  ThumbsUp,
} from "lucide-react";
import {
  communityConnectionApi,
  type CommunityConnectionStatus,
} from "@/api/modules/community";
import { openExternalLink } from "@/utils/openExternalLink";
import { communityErrorKey } from "@/utils/communityError";
import { communityPostsApi, type Post } from "./api";
import { PostBody } from "./PostBody";
import { mediaUrl } from "./media";
import { EditPostModal } from "./EditPostModal";
import { Discussion } from "./Discussion";
import styles from "./index.module.less";

export function QuestionStatus({ post }: { post: Post }) {
  const { t } = useTranslation();
  return post.article_type === "question" && post.qa_status === "solved" ? (
    <span className={styles.solvedStatus}>
      <CircleCheck size={14} aria-hidden="true" />
      {t("communityPage.solved")}
    </span>
  ) : null;
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
  const [tab, setTab] = useState<"answer" | "comment">("answer");
  const [focusRequest, setFocusRequest] = useState(0);
  const question = post?.article_type === "question";
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
    setTab(target);
    setFocusRequest((v) => v + 1);
  };
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
      <Link className={styles.backLink} to={`/market?${backParams}`}>
        <ArrowLeft size={16} aria-hidden="true" />
        {t("communityPage.back")}
      </Link>
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
      <Spin spinning={loading}>
        {post && (
          <>
            <article className={styles.articleCard}>
              <div className={styles.articleEyebrow}>
                {post.article_type_label ||
                  t(
                    question
                      ? "communityPage.question"
                      : "communityPage.article",
                  )}{" "}
                <QuestionStatus post={post} />
              </div>
              <h1 className={styles.articleTitle}>{post.title}</h1>
              <div className={styles.authorRow}>
                <Avatar size={32} src={mediaUrl(post.author_avatar_url)}>
                  {post.author_name?.slice(0, 1)}
                </Avatar>
                <span className={styles.authorName}>{post.author_name}</span>
                <time className={styles.meta}>
                  {post.published_at?.slice(0, 10)}
                </time>
              </div>
              {ownPost && (
                <div className={styles.ownerActions}>
                  <Button
                    size="small"
                    icon={<Pencil size={14} />}
                    disabled={!!busy}
                    title={nativeEdit ? t("communityPage.editHelp") : undefined}
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
              <PostBody post={post} />
              <div className={styles.articleActions}>
                {question && (
                  <Button
                    type="primary"
                    icon={<MessageSquare size={16} aria-hidden="true" />}
                    onClick={() => focusDiscussion("answer")}
                  >
                    {t("communityPage.writeAnswer")}
                  </Button>
                )}
                <Button
                  aria-pressed={!!post.liked}
                  className={post.liked ? styles.activeAction : undefined}
                  loading={busy === "like"}
                  disabled={!!busy}
                  icon={<ThumbsUp size={16} aria-hidden="true" />}
                  onClick={() => void interact("like")}
                >
                  {t(question ? "communityPage.helpful" : "communityPage.like")}{" "}
                  {post.like_count || ""}
                </Button>
                {!question && (
                  <Button
                    aria-pressed={!!post.favorited}
                    className={post.favorited ? styles.activeAction : undefined}
                    loading={busy === "favorite"}
                    disabled={!!busy}
                    icon={<Bookmark size={16} aria-hidden="true" />}
                    onClick={() => void interact("favorite")}
                  >
                    {t(
                      post.favorited
                        ? "communityPage.favorited"
                        : "communityPage.favorite",
                    )}{" "}
                    {post.favorite_count || ""}
                  </Button>
                )}
                <Button
                  type="text"
                  icon={<MessageSquare size={16} aria-hidden="true" />}
                  onClick={() => focusDiscussion("comment")}
                >
                  {t(
                    question
                      ? "communityPage.commentQuestion"
                      : "communityPage.comments",
                  )}
                </Button>
                <Button
                  type="text"
                  icon={<Share2 size={16} aria-hidden="true" />}
                  onClick={() => void share()}
                >
                  {t("communityPage.share")}
                </Button>
                <Button
                  type="text"
                  icon={<Flag size={14} aria-hidden="true" />}
                  title={t("communityPage.reportHelp")}
                  onClick={() => {
                    openExternalLink(platformUrl);
                    message.info(t("communityPage.reportHelp"));
                  }}
                >
                  {t("communityPage.report")}
                  <ExternalLink size={12} aria-hidden="true" />
                </Button>
              </div>
              {actionError && <Alert type="error" message={t(actionError)} />}
            </article>
            <div className={styles.discussionCard}>
              {question && (
                <Segmented
                  className={styles.discussionTabs}
                  aria-label={t("communityPage.discussionType")}
                  value={tab}
                  options={[
                    { value: "answer", label: t("communityPage.answers") },
                    {
                      value: "comment",
                      label: t("communityPage.commentQuestion"),
                    },
                  ]}
                  onChange={(value) => setTab(value as "answer" | "comment")}
                />
              )}
              {question ? (
                <>
                  <div hidden={tab !== "answer"}>
                    <Discussion
                      id={id}
                      kind="answer"
                      connection={connection}
                      acceptedIds={
                        post.accepted_comment_ids ||
                        (post.accepted_comment_id
                          ? [post.accepted_comment_id]
                          : [])
                      }
                      focusRequest={tab === "answer" ? focusRequest : 0}
                    />
                  </div>
                  <div hidden={tab !== "comment"}>
                    <Discussion
                      id={id}
                      kind="comment"
                      connection={connection}
                      focusRequest={tab === "comment" ? focusRequest : 0}
                    />
                  </div>
                </>
              ) : (
                <Discussion
                  id={id}
                  connection={connection}
                  focusRequest={focusRequest}
                />
              )}
            </div>
          </>
        )}
      </Spin>
    </>
  );
}
