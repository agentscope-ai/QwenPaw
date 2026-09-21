import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Pagination,
  Segmented,
  Select,
  Spin,
} from "antd";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import {
  communityConnectionApi,
  type CommunityConnectionStatus,
} from "@/api/modules/community";
import { MarketplaceHeader } from "../components/MarketplaceHeader";
import { communityPostsApi, type Post, type Comment, type Page } from "./api";
import { isCustomEmoji, markdownWithCustomEmoji } from "./customEmoji";
import { COMMUNITY_FILTER_TYPES, COMMUNITY_SORTS } from "@/constants/community";
import {
  openExternalLinkChecked,
  openExternalLink,
} from "@/utils/openExternalLink";
import { communityErrorKey } from "@/utils/communityError";
import { useAppMessage } from "@/hooks/useAppMessage";
import { ExternalLink } from "lucide-react";
import styles from "./index.module.less";

function CommunityAnchor({
  href,
  children,
}: {
  href?: string;
  children?: React.ReactNode;
}) {
  return (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        if (href)
          openExternalLink(
            new URL(href, "https://platform.agentscope.io").href,
          );
      }}
    >
      {children}
    </a>
  );
}

export function PostBody({ post }: { post: Post }) {
  const html = DOMPurify.sanitize(post.body_html || "", {
    USE_PROFILES: { html: true },
    FORBID_TAGS: [
      "style",
      "form",
      "input",
      "button",
      "iframe",
      "video",
      "audio",
    ],
    FORBID_ATTR: ["style", "id", "name", "srcset"],
  });
  return html ? (
    <div
      className={styles.body}
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={(event) => {
        const link = (event.target as Element).closest("a");
        const href = link?.getAttribute("href");
        if (!href || href.startsWith("#")) return;
        event.preventDefault();
        openExternalLink(new URL(href, "https://platform.agentscope.io").href);
      }}
    />
  ) : (
    <div className={styles.body}>
      <ReactMarkdown components={{ a: CommunityAnchor }}>
        {post.body_text || post.summary || ""}
      </ReactMarkdown>
    </div>
  );
}

function CommentThread({
  comment,
  onReply,
}: {
  comment: Comment;
  onReply: (comment: Comment) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.comment}>
      <div className={styles.meta}>
        {comment.author_name} · {comment.created_at?.replace("T", " ")}
      </div>
      <ReactMarkdown
        components={{
          a: CommunityAnchor,
          img: ({ src, alt }) => (
            <img
              src={src}
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
      <Button type="text" size="small" onClick={() => onReply(comment)}>
        {t("communityPage.reply")}
      </Button>
      {comment.replies?.map((reply) => (
        <CommentThread key={reply.id} comment={reply} onReply={onReply} />
      ))}
    </div>
  );
}

function PostDetail({ id }: { id: string }) {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const backParams = new URLSearchParams(params);
  backParams.delete("post");
  const [post, setPost] = useState<Post>();
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
  const [connection, setConnection] = useState<CommunityConnectionStatus>();
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    Promise.all([
      communityPostsApi.detail(id, controller.signal),
      communityPostsApi.comments(id, page, controller.signal),
      communityConnectionApi.status(controller.signal).catch(() => undefined),
    ])
      .then(([detail, replies, status]) => {
        if (!controller.signal.aborted) {
          setPost(detail);
          setComments(replies);
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
  }, [id, page, reload]);
  const send = async () => {
    if (!draft.trim() || !connection?.account || sending) return;
    setSending(true);
    setSendError(undefined);
    try {
      await communityPostsApi.comment(
        id,
        draft.trim(),
        connection.account.id,
        reply?.id,
      );
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
    <>
      <Link to={`/market?${backParams}`}>← {t("communityPage.back")}</Link>
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
      <Spin spinning={loading}>
        {post && (
          <article>
            <h1>{post.title}</h1>
            <div className={styles.meta}>
              {post.author_name} · {post.published_at?.replace("T", " ")} ·{" "}
              {post.article_type_label}
            </div>
            <PostBody post={post} />
            <section
              className={styles.discussion}
              aria-label={t("communityPage.comments")}
            >
              <h2>
                {t("communityPage.comments")} ({comments.total})
              </h2>
              {connection?.status === "connected" ? (
                <div className={styles.composer}>
                  {reply && (
                    <div>
                      {t("communityPage.replyTo", { name: reply.author_name })}{" "}
                      <Button type="text" onClick={() => setReply(undefined)}>
                        {t("communityPage.cancelReply")}
                      </Button>
                    </div>
                  )}
                  <label htmlFor="community-comment">
                    {t("communityPage.writeComment")}
                  </label>
                  <Input.TextArea
                    id="community-comment"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    autoSize={{ minRows: 3, maxRows: 12 }}
                    maxLength={65536}
                    disabled={sending}
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
                    {t("communityPage.send")}
                  </Button>
                </div>
              ) : (
                <Link to="/settings/community">
                  {t("communityPage.connect")}
                </Link>
              )}
              {!comments.items.length && (
                <Empty
                  description={t("communityPage.noComments")}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              )}
              {comments.items.map((comment) => (
                <CommentThread
                  key={comment.id}
                  comment={comment}
                  onReply={setReply}
                />
              ))}
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
          </article>
        )}
      </Spin>
    </>
  );
}

export default function CommunityPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const openEditor = (path: "write" | "ask") => {
    void openExternalLinkChecked(
      `https://platform.agentscope.io/community/${path}`,
    ).catch((err) => message.error(t(communityErrorKey(err))));
  };
  const [params, setParams] = useSearchParams();
  const id = params.get("post");
  const page = Math.max(1, Number(params.get("page")) || 1);
  const keyword = params.get("keyword") || "";
  const requestedType = params.get("type") || "all";
  const type = COMMUNITY_FILTER_TYPES.some((value) => value === requestedType)
    ? requestedType
    : "all";
  const sort = params.get("sort") === "latest" ? "latest" : "recommended";
  const [data, setData] = useState<Page<Post>>({ items: [], total: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (id) return;
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    communityPostsApi
      .list(page, keyword, type, sort, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(communityErrorKey(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [id, page, keyword, type, sort, reload]);
  const update = (values: Record<string, string>) =>
    setParams({ tab: "community", keyword, type, sort, page: "1", ...values });
  const items = [
    ...(page === 1 ? data.pinned || [] : []),
    ...data.items,
  ].filter(
    (post, index, all) =>
      all.findIndex((item) => item.id === post.id) === index,
  );
  return (
    <div className={styles.page}>
      <MarketplaceHeader activeSection="community" />
      <div className={styles.scroll}>
        <div className={styles.content}>
          {id ? (
            <PostDetail key={id} id={id} />
          ) : (
            <>
              <div className={styles.heading}>
                <div>
                  <h1>{t("communityFeedback.community")}</h1>
                  <p className={styles.meta}>
                    {t("communityPage.description")}
                  </p>
                </div>
                <div>
                  <Link to="/settings/community">
                    {t("communityPage.account")}
                  </Link>
                  <Button
                    style={{ marginLeft: 16 }}
                    onClick={() => openEditor("ask")}
                  >
                    {t("communityPage.askOnPlatform")}
                  </Button>
                  <Button
                    type="primary"
                    style={{ marginLeft: 16 }}
                    onClick={() => openEditor("write")}
                    icon={<ExternalLink size={14} aria-hidden="true" />}
                  >
                    {t("communityPage.writeOnPlatform")}
                  </Button>
                </div>
              </div>
              <p className={styles.meta}>{t("communityPage.editorHelp")}</p>
              <div className={styles.toolbar}>
                <Segmented
                  aria-label={t("communityPage.sort")}
                  value={sort}
                  options={COMMUNITY_SORTS.map((value) => ({
                    value,
                    label: t(`communityPage.${value}`),
                  }))}
                  onChange={(value) => update({ sort: String(value) })}
                />
                <Input.Search
                  key={keyword}
                  defaultValue={keyword}
                  placeholder={t("communityPage.search")}
                  aria-label={t("communityPage.search")}
                  onSearch={(value) => update({ keyword: value })}
                  allowClear
                />
                <Select
                  aria-label={t("communityPage.type")}
                  value={type}
                  onChange={(value) => update({ type: value })}
                  options={COMMUNITY_FILTER_TYPES.map((value) => ({
                    value,
                    label: t(`communityPage.${value}`),
                  }))}
                />
                <Button onClick={() => setReload((value) => value + 1)}>
                  {t("communityPage.refresh")}
                </Button>
              </div>
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
              <Spin spinning={loading}>
                <div className={styles.feed}>
                  {!loading && !error && !items.length && (
                    <Empty description={t("communityPage.empty")} />
                  )}
                  {items.map((post) => (
                    <Link
                      className={styles.post}
                      key={post.id}
                      to={`/market?tab=community&post=${encodeURIComponent(
                        post.id,
                      )}&${new URLSearchParams({
                        sort,
                        type,
                        keyword,
                        page: String(page),
                      })}`}
                    >
                      <div className={styles.meta}>
                        {post.author_name} · {post.article_type_label}
                      </div>
                      <h2>{post.title}</h2>
                      <p>{post.summary}</p>
                      <div className={styles.meta}>
                        {post.published_at?.slice(0, 10)} ·{" "}
                        {t("communityPage.commentCount", {
                          count: post.comment_count || 0,
                        })}
                      </div>
                    </Link>
                  ))}
                </div>
              </Spin>
              {data.total > 20 && (
                <Pagination
                  current={page}
                  pageSize={20}
                  total={data.total}
                  showSizeChanger={false}
                  onChange={(value) => update({ page: String(value) })}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
