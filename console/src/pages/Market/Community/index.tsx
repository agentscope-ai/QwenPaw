import { lazy, Suspense, useEffect, useState } from "react";
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
import { Avatar } from "antd";
import { MessageSquare, ThumbsUp, FilePenLine } from "lucide-react";
import { MarketplaceHeader } from "../components/MarketplaceHeader";
import { communityPostsApi, type Post, type Page } from "./api";
import { PostDetail, QuestionStatus } from "./PostDetail";
import { mediaUrl } from "./media";
export { PostBody } from "./PostBody";
import { COMMUNITY_FILTER_TYPES, COMMUNITY_SORTS } from "@/constants/community";
import { communityErrorKey } from "@/utils/communityError";
import styles from "./index.module.less";
import { communityConnectionApi } from "@/api/modules/community";
import {
  latestWritingSession,
  type WritingSession,
} from "@/pages/CommunityFeedback/writingSession";

const PostComposer = lazy(() =>
  import("@/pages/CommunityFeedback/PostComposer").then((module) => ({
    default: module.PostComposer,
  })),
);

const DraftLibrary = lazy(() =>
  import("@/pages/CommunityFeedback/DraftLibrary").then((module) => ({
    default: module.DraftLibrary,
  })),
);

export default function CommunityPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const showingDrafts = params.get("drafts") === "1";
  const requestedEditor = params.get("compose");
  const editor =
    requestedEditor === "question" || requestedEditor === "discussion"
      ? requestedEditor
      : undefined;
  const [resumable, setResumable] = useState<WritingSession>();
  useEffect(() => {
    let active = true;
    if (!editor) {
      void communityConnectionApi
        .status()
        .then((status) => {
          if (active)
            setResumable(
              status.status === "connected" && status.account
                ? latestWritingSession(status.account.id)
                : undefined,
            );
        })
        .catch(() => {
          if (active) setResumable(undefined);
        });
    }
    return () => {
      active = false;
    };
  }, [editor, showingDrafts]);
  const openEditor = (path: "write" | "ask") => {
    const next = new URLSearchParams(params);
    next.delete("post");
    next.delete("drafts");
    next.delete("draft");
    next.set("compose", path === "ask" ? "question" : "discussion");
    setParams(next);
  };
  const closeEditor = () => {
    const next = new URLSearchParams(params);
    next.delete("compose");
    next.delete("draft");
    next.delete("drafts");
    setParams(next, { replace: true });
  };
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
    if (id || editor || showingDrafts) return;
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
  }, [id, editor, showingDrafts, page, keyword, type, sort, reload]);
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
      {editor ? (
        <Suspense fallback={<Spin />}>
          <PostComposer
            key={`${editor}:${params.get("draft") || "new"}`}
            draftId={params.get("draft") || undefined}
            presentation="page"
            initialType={editor}
            onClose={closeEditor}
          />
        </Suspense>
      ) : showingDrafts ? (
        <div className={styles.scroll}>
          <Suspense fallback={<Spin />}>
            <DraftLibrary
              onBack={closeEditor}
              onOpen={(draft) => {
                const next = new URLSearchParams(params);
                next.delete("drafts");
                next.set(
                  "compose",
                  draft.type === "question" ? "question" : "discussion",
                );
                next.set("draft", draft.id);
                setParams(next);
              }}
            />
          </Suspense>
        </div>
      ) : (
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
                  <div className={styles.headingActions}>
                    <Link to="/settings/community">
                      {t("communityPage.account")}
                    </Link>
                    <Button
                      onClick={() => {
                        const next = new URLSearchParams(params);
                        next.set("drafts", "1");
                        setParams(next);
                      }}
                    >
                      {t("communityDrafts.title")}
                    </Button>
                    {resumable && (
                      <Button
                        icon={<FilePenLine size={16} />}
                        onClick={() => {
                          const next = new URLSearchParams(params);
                          next.delete("post");
                          next.delete("drafts");
                          next.delete("draft");
                          next.set("compose", resumable.initialType);
                          // Reopen the original in-window session, including unsaved edits.
                          if (resumable.id && resumable.draftId)
                            next.set("draft", resumable.draftId);
                          setParams(next);
                        }}
                      >
                        {t("communityAssist.resumeWriting")}
                      </Button>
                    )}
                    <Button onClick={() => openEditor("ask")}>
                      {t("communityPage.askOnPlatform")}
                    </Button>
                    <Button type="primary" onClick={() => openEditor("write")}>
                      {t("communityPage.writeOnPlatform")}
                    </Button>
                  </div>
                </div>
                <p className={`${styles.meta} ${styles.editorHelp}`}>
                  {t("communityPage.editorHelp")}
                </p>
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
                        <div className={styles.authorRow}>
                          <Avatar
                            size={28}
                            src={mediaUrl(post.author_avatar_url)}
                          >
                            {post.author_name?.slice(0, 1)}
                          </Avatar>
                          <span className={styles.authorName}>
                            {post.author_name}
                          </span>
                          <span className={styles.typeBadge}>
                            {post.article_type_label}
                          </span>
                        </div>
                        <div className={styles.postTitle}>
                          <h2>{post.title}</h2>
                          <QuestionStatus post={post} />
                        </div>
                        <p>{post.summary}</p>
                        <div className={styles.postStats}>
                          <time>{post.published_at?.slice(0, 10)}</time>
                          <span>
                            <MessageSquare size={14} aria-hidden="true" />
                            {t("communityPage.commentCount", {
                              count: post.comment_count || 0,
                            })}
                          </span>
                          {!!post.like_count && (
                            <span>
                              <ThumbsUp size={14} aria-hidden="true" />
                              {post.like_count}
                            </span>
                          )}
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
      )}
    </div>
  );
}
