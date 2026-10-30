import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Alert,
  Avatar,
  Button,
  Dropdown,
  Empty,
  Input,
  Spin,
  Tabs,
} from "antd";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MessageSquare, RefreshCw, ThumbsUp } from "lucide-react";
import {
  SparkDownLine,
  SparkDocumentLine,
  SparkEditLine,
  SparkMagicNoteLine,
  SparkSearchLine,
  SparkUserLine,
  SparkVisableLine,
} from "@agentscope-ai/icons";
import { MarketplaceHeader } from "../components/MarketplaceHeader";
import { communityPostsApi, type Post } from "./api";
import AuthorBadges from "./AuthorBadges";
import { PostDetail, QuestionStatus } from "./PostDetail";
import { mediaUrl } from "./media";
export { PostBody } from "./PostBody";
import {
  COMMUNITY_FILTER_TYPES,
  COMMUNITY_POST_TYPES,
  communityPostActionForType,
  communitySortsForType,
} from "@/constants/community";
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

function dedupePosts(posts: Post[]) {
  return posts.filter(
    (post, index, all) =>
      all.findIndex((item) => item.id === post.id) === index,
  );
}

/** Mirrors agentscope-platform-front: "M月D日" for zh, "Mon D" otherwise. */
function formatFeedDate(value: string | undefined, locale: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  if (locale.startsWith("zh"))
    return `${date.getMonth() + 1}月${date.getDate()}日`;
  return date.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

/** Sentinel row that triggers the next page when scrolled into view. */
function LoadMoreSentinel({ onVisible }: { onVisible: () => void }) {
  const { t } = useTranslation();
  const nodeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = nodeRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onVisible();
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [onVisible]);
  return (
    <div ref={nodeRef} className={styles.sentinel}>
      {t("common.loading")}
    </div>
  );
}

export default function CommunityPage() {
  const { t, i18n } = useTranslation();
  const [params, setParams] = useSearchParams();
  const showingDrafts = params.get("drafts") === "1";
  const requestedEditor = params.get("compose");
  const editor =
    requestedEditor === "question" || requestedEditor === "discussion"
      ? requestedEditor
      : undefined;
  const [resumable, setResumable] = useState<WritingSession>();
  const [accountName, setAccountName] = useState<string | null>(null);
  const [accountAvatar, setAccountAvatar] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    if (!editor) {
      void communityConnectionApi
        .status()
        .then((status) => {
          if (!active) return;
          const connected =
            status.status === "connected" && status.account
              ? status.account
              : null;
          setAccountName(connected ? connected.display_name : null);
          setAccountAvatar(connected ? connected.avatar_url ?? null : null);
          setResumable(
            connected ? latestWritingSession(connected.id) : undefined,
          );
        })
        .catch(() => {
          if (active) {
            setResumable(undefined);
            setAccountName(null);
            setAccountAvatar(null);
          }
        });
    }
    return () => {
      active = false;
    };
  }, [editor, showingDrafts]);
  const openEditor = (path: "write" | "ask", articleType?: string) => {
    const next = new URLSearchParams(params);
    next.delete("post");
    next.delete("drafts");
    next.delete("draft");
    next.set("compose", path === "ask" ? "question" : "discussion");
    if (articleType) next.set("article", articleType);
    else next.delete("article");
    setParams(next);
  };
  const closeEditor = () => {
    const next = new URLSearchParams(params);
    next.delete("compose");
    next.delete("draft");
    next.delete("drafts");
    next.delete("article");
    setParams(next, { replace: true });
  };
  const id = params.get("post");
  const keyword = params.get("keyword") || "";
  const requestedType = params.get("type") || "all";
  const type = COMMUNITY_FILTER_TYPES.some((value) => value === requestedType)
    ? requestedType
    : "all";
  const requestedSort = params.get("sort") || "recommended";
  const sort = (communitySortsForType(type) as string[]).includes(requestedSort)
    ? requestedSort
    : "recommended";
  const postAction = communityPostActionForType(type);
  const requestedArticle = params.get("article") || "";
  const articleType = (COMMUNITY_POST_TYPES as readonly string[]).includes(
    requestedArticle,
  )
    ? requestedArticle
    : undefined;
  const [entries, setEntries] = useState<Post[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [autoLoadBlocked, setAutoLoadBlocked] = useState(false);
  const [error, setError] = useState<string>();
  const [reload, setReload] = useState(0);
  const pageRef = useRef(1);
  const loadingMoreRef = useRef(false);
  const pageControllerRef = useRef<AbortController | null>(null);
  useEffect(() => {
    if (id || editor || showingDrafts) return;
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    communityPostsApi
      .list(1, keyword, type, sort, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setEntries(dedupePosts([...(result.pinned || []), ...result.items]));
        setTotal(result.total);
        pageRef.current = 1;
        setAutoLoadBlocked(false);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(communityErrorKey(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      // An in-flight pagination request from the previous filter must not
      // write its pages into the new list either.
      pageControllerRef.current?.abort();
    };
  }, [id, editor, showingDrafts, keyword, type, sort, reload]);
  const loadNextPage = useCallback(() => {
    if (loading || loadingMoreRef.current || entries.length >= total) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    const controller = new AbortController();
    pageControllerRef.current = controller;
    const before = entries;
    communityPostsApi
      .list(pageRef.current + 1, keyword, type, sort, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        const merged = dedupePosts([...before, ...result.items]);
        setEntries(merged);
        // The platform total can outrun the pages it actually serves: a
        // page that adds nothing means the feed ended, so clamp the total
        // or the sentinel would keep showing "loading" forever.
        setTotal(
          merged.length === before.length ? merged.length : result.total,
        );
        pageRef.current += 1;
      })
      .catch(() => {
        // Stop the sentinel from retrying; the manual button stays available.
        if (!controller.signal.aborted) setAutoLoadBlocked(true);
      })
      .finally(() => {
        // Clear the flags even when aborted, or a cancelled request would
        // wedge pagination for the next query.
        if (pageControllerRef.current === controller)
          pageControllerRef.current = null;
        loadingMoreRef.current = false;
        setLoadingMore(false);
      });
  }, [entries, keyword, loading, sort, total, type]);
  const update = (values: Record<string, string>) =>
    setParams({ tab: "community", keyword, type, sort, ...values });
  const changeType = (next: string) => {
    const nextSort = (communitySortsForType(next) as string[]).includes(sort)
      ? sort
      : "recommended";
    update({ type: next, sort: nextSort });
  };
  const openDrafts = () => {
    const next = new URLSearchParams(params);
    next.delete("post");
    next.delete("draft");
    // The composer view outranks the draft library, so leaving it must
    // clear compose (and the editor-only board) or the click looks dead.
    next.delete("compose");
    next.delete("article");
    next.set("drafts", "1");
    setParams(next);
  };
  const postMenuItems = [
    {
      key: "ask",
      label: t("communityPage.askOnPlatform"),
      Icon: SparkEditLine,
    },
    {
      key: "write",
      label: t("communityPage.writeOnPlatform"),
      Icon: SparkMagicNoteLine,
    },
    {
      key: "drafts",
      label: t("communityDrafts.title"),
      Icon: SparkDocumentLine,
    },
    ...(resumable
      ? [
          {
            key: "resume",
            label: t("communityAssist.resumeWriting"),
            Icon: SparkEditLine,
          },
        ]
      : []),
  ];
  const handlePostMenu = ({ key }: { key: string }) => {
    if (key === "ask") openEditor("ask");
    else if (key === "write") openEditor("write");
    else if (key === "drafts") openDrafts();
    else if (key === "resume" && resumable) {
      const next = new URLSearchParams(params);
      next.delete("post");
      next.delete("drafts");
      next.delete("draft");
      // The restored session's own type wins; a stale board from the
      // current editor would override it in PostComposer.
      next.delete("article");
      next.set("compose", resumable.initialType);
      // Reopen the original in-window session, including unsaved edits.
      if (resumable.id && resumable.draftId)
        next.set("draft", resumable.draftId);
      setParams(next);
    }
  };
  const postDropdown = (label: string) => (
    <Dropdown
      trigger={["click"]}
      popupRender={() => (
        <div className={styles.postMenu}>
          {postMenuItems.map(({ key, label: itemLabel, Icon }) => (
            <button
              key={key}
              type="button"
              className={styles.postMenuItem}
              onClick={() => handlePostMenu({ key })}
            >
              <span className={styles.postMenuIcon}>
                <Icon size={22} />
              </span>
              <span className={styles.postMenuLabel}>{itemLabel}</span>
            </button>
          ))}
        </div>
      )}
    >
      <Button type="primary" className={styles.postBtn}>
        {label}
        <SparkDownLine />
      </Button>
    </Dropdown>
  );
  const headerActions = (
    <div className={styles.headerActions}>
      <Link to="/settings/community" className={styles.accountBtn}>
        <Avatar
          size={20}
          src={mediaUrl(accountAvatar ?? undefined)}
          icon={<SparkUserLine />}
        />
        <span className={styles.accountLabel} title={accountName || undefined}>
          {accountName || t("communityPage.account")}
        </span>
      </Link>
      {postDropdown(t("communityPage.goPost"))}
    </div>
  );
  const locale = i18n.resolvedLanguage || i18n.language;
  return (
    <div className={styles.page}>
      <MarketplaceHeader activeSection="community" extra={headerActions} />
      {editor ? (
        <Suspense fallback={<Spin />}>
          <PostComposer
            key={`${editor}:${params.get("draft") || "new"}`}
            draftId={params.get("draft") || undefined}
            presentation="page"
            initialType={editor}
            initialArticleType={articleType}
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
          {id ? (
            <PostDetail key={id} id={id} />
          ) : (
            <div className={styles.content}>
              <div className={styles.categoryRow}>
                {COMMUNITY_FILTER_TYPES.map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={type === value}
                    className={`${styles.categoryChip} ${
                      type === value ? styles.categoryChipActive : ""
                    }`}
                    onClick={() => changeType(value)}
                  >
                    {t(`communityPage.${value}`)}
                  </button>
                ))}
              </div>
              <div className={styles.feedToolbar}>
                <Tabs
                  className={styles.sortTabs}
                  activeKey={sort}
                  items={communitySortsForType(type).map((value) => ({
                    key: value,
                    label: t(`communityPage.${value}`),
                  }))}
                  onChange={(value) => update({ sort: value })}
                  aria-label={t("communityPage.sort")}
                />
                <div className={styles.feedActions}>
                  <Input
                    key={keyword}
                    defaultValue={keyword}
                    allowClear
                    prefix={<SparkSearchLine />}
                    placeholder={t("communityPage.search")}
                    aria-label={t("communityPage.search")}
                    className={styles.searchInput}
                    onPressEnter={(e) =>
                      update({ keyword: e.currentTarget.value })
                    }
                    onChange={(e) => {
                      if (!e.target.value) update({ keyword: "" });
                    }}
                  />
                  {postAction &&
                    (postAction.kind === "menu" ? (
                      postDropdown(t(postAction.labelKey))
                    ) : (
                      <Button
                        type="primary"
                        className={styles.postBtn}
                        onClick={() =>
                          postAction.kind === "ask"
                            ? openEditor("ask")
                            : openEditor("write", postAction.articleType)
                        }
                      >
                        {t(postAction.labelKey)}
                      </Button>
                    ))}
                  <Button
                    type="default"
                    className={styles.refreshBtn}
                    icon={<RefreshCw size={14} />}
                    onClick={() => setReload((value) => value + 1)}
                    disabled={loading}
                    aria-label={t("communityPage.refresh")}
                    title={t("communityPage.refresh")}
                  />
                </div>
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
              <Spin spinning={loading && Boolean(entries.length)} size="large">
                {loading && !entries.length && (
                  <div className={styles.spinFill}>
                    <Spin size="large" />
                  </div>
                )}
                <div className={styles.feed}>
                  {!loading && !error && !entries.length && (
                    <Empty description={t("communityPage.empty")} />
                  )}
                  {entries.map((post) => {
                    const dateText = formatFeedDate(
                      post.published_at || post.created_at,
                      locale,
                    );
                    const dateLabel = dateText
                      ? post.article_type === "question"
                        ? t("communityPage.askedOn", { date: dateText })
                        : t("communityPage.publishedOn", { date: dateText })
                      : "";
                    return (
                      <Link
                        className={styles.post}
                        key={post.id}
                        to={`/market?tab=community&post=${encodeURIComponent(
                          post.id,
                        )}&${new URLSearchParams({
                          sort,
                          type,
                          keyword,
                        })}`}
                      >
                        <div className={styles.postMain}>
                          <div className={styles.postContent}>
                            <div className={styles.postTitle}>
                              <h2>{post.title}</h2>
                              {dateLabel && (
                                <span className={styles.postDate}>
                                  {dateLabel}
                                </span>
                              )}
                            </div>
                            {post.summary && (
                              <p className={styles.postSummary}>
                                {post.summary}
                              </p>
                            )}
                          </div>
                          {mediaUrl(post.cover_url) && (
                            <img
                              className={styles.postCover}
                              src={mediaUrl(post.cover_url)}
                              alt=""
                            />
                          )}
                        </div>
                        <div className={styles.postFooter}>
                          <div className={styles.postStats}>
                            {post.article_type === "question" ? (
                              <QuestionStatus post={post} />
                            ) : (
                              !!post.author_name && (
                                <span className={styles.authorName}>
                                  {post.author_name}
                                  <AuthorBadges
                                    officialIconOnly
                                    identity_badge={post.identity_badge}
                                    identity_badges={post.identity_badges}
                                  />
                                </span>
                              )
                            )}
                            {(post.article_type === "question" ||
                              post.author_name) && (
                              <span className={styles.statDivider} aria-hidden>
                                |
                              </span>
                            )}
                            <span>
                              <ThumbsUp size={14} aria-hidden="true" />
                              {post.like_count || 0}
                            </span>
                            <span>
                              <MessageSquare size={14} aria-hidden="true" />
                              {post.comment_count || 0}
                            </span>
                            {typeof post.view_count === "number" && (
                              <span>
                                <SparkVisableLine
                                  size={14}
                                  aria-hidden="true"
                                />
                                {post.view_count}
                              </span>
                            )}
                          </div>
                          {!!post.tags?.length && (
                            <div className={styles.postTags}>
                              {post.tags.slice(0, 4).map((tag) => (
                                <span key={tag} className={styles.postTag}>
                                  {tag}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </Link>
                    );
                  })}
                </div>
              </Spin>
              {!loading && entries.length > 0 && (
                <div className={styles.loadMoreRow}>
                  {entries.length < total && autoLoadBlocked ? (
                    <Button onClick={loadNextPage} loading={loadingMore}>
                      {t("market.loadMore")}
                    </Button>
                  ) : entries.length < total ? (
                    <LoadMoreSentinel
                      key={entries.length}
                      onVisible={loadNextPage}
                    />
                  ) : (
                    <span className={styles.noMoreText}>
                      {t("market.noMoreResults")}
                    </span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
