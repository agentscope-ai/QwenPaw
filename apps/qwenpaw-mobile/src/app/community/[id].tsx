import { MobileAlert } from "@/components/MobileAlert";
import { router, useLocalSearchParams } from "expo-router";
import {
  BadgeCheck,
  ChevronLeft,
  Eye,
  Heart,
  MessageCircle,
  RefreshCw,
  Send,
} from "lucide-react-native";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getPlatformAccessToken } from "../../api/platform";
import {
  communityArticleUrl,
  createCommunityComment,
  getCommunityArticle,
  getCommunityComments,
  likeCommunityArticle,
} from "../../features/community/api";
import { CommunityAvatar } from "../../features/community/components/CommunityAvatar";
import {
  formatCommunityDate,
  normalizeCommunityText,
  removeCommunityEmoji,
} from "../../features/community/model";
import type {
  CommunityArticle,
  CommunityComment,
} from "../../features/community/types";
import { colors, radius, spacing } from "../../theme/tokens";

export default function CommunityArticleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const articleId = Array.isArray(id) ? id[0] : id;
  const [article, setArticle] = useState<CommunityArticle | null>(null);
  const [comments, setComments] = useState<CommunityComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [commentText, setCommentText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    if (!articleId) return;
    setLoading(true);
    setError(null);
    try {
      const [nextArticle, nextComments] = await Promise.all([
        getCommunityArticle(articleId),
        getCommunityComments(articleId),
      ]);
      setArticle(nextArticle);
      setComments(nextComments.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文章加载失败");
    } finally {
      setLoading(false);
    }
  }, [articleId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  const share = useCallback(() => {
    if (!article) return;
    void Share.share({
      message: `${article.title}\n${communityArticleUrl(article.id)}`,
      url: communityArticleUrl(article.id),
    });
  }, [article]);

  const promptPlatformLogin = useCallback(() => {
    MobileAlert.alert(
      "需要登录 AgentScope Platform",
      "点赞和评论会同步到线上社区，请先完成 Platform 登录。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "登录",
          onPress: () => router.push("/community/login"),
        },
      ],
    );
  }, []);

  const like = useCallback(async () => {
    if (!article) return;
    if (!await getPlatformAccessToken()) {
      promptPlatformLogin();
      return;
    }
    try {
      const updated = await likeCommunityArticle(article.id);
      setArticle((current) => current ? {
        ...current,
        liked: updated.liked,
        like_count: updated.like_count,
      } : current);
    } catch (caught) {
      MobileAlert.alert(
        "点赞失败",
        caught instanceof Error ? caught.message : "请稍后重试",
      );
    }
  }, [article, promptPlatformLogin]);

  const submitComment = useCallback(async () => {
    if (!article || !commentText.trim() || submitting) return;
    if (!await getPlatformAccessToken()) {
      promptPlatformLogin();
      return;
    }
    setSubmitting(true);
    try {
      const comment = await createCommunityComment(article.id, commentText);
      setComments((current) => [comment, ...current]);
      setArticle((current) => current
        ? { ...current, comment_count: current.comment_count + 1 }
        : current);
      setCommentText("");
    } catch (caught) {
      MobileAlert.alert(
        "评论失败",
        caught instanceof Error ? caught.message : "请稍后重试",
      );
    } finally {
      setSubmitting(false);
    }
  }, [article, commentText, promptPlatformLogin, submitting]);

  const header = useMemo(() => article ? (
    <ArticleContent article={article} />
  ) : null, [article]);

  return (
    <SafeAreaView edges={["top", "bottom"]} style={styles.root}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
      <View style={styles.shell}>
        <View style={styles.header}>
          <Pressable
            accessibilityLabel="返回"
            hitSlop={8}
            onPress={() => router.back()}
            style={styles.headerAction}
          >
            <ChevronLeft color={colors.ink} size={25} />
          </Pressable>
          <Text numberOfLines={1} style={styles.headerTitle}>社区详情</Text>
          <Pressable
            accessibilityLabel="分享"
            hitSlop={8}
            onPress={share}
            style={styles.headerAction}
          >
            <Send color={colors.ink} size={21} />
          </Pressable>
        </View>

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.accent} />
            <Text style={styles.stateCopy}>正在加载文章与评论</Text>
          </View>
        ) : error || !article ? (
          <View style={styles.center}>
            <RefreshCw color={colors.accent} size={27} />
            <Text style={styles.stateTitle}>文章暂时无法打开</Text>
            <Text style={styles.stateCopy}>{error || "文章不存在或已下架"}</Text>
            <Pressable onPress={() => void load()} style={styles.retry}>
              <Text style={styles.retryLabel}>重新加载</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <FlatList
              contentContainerStyle={styles.list}
              data={comments}
              ItemSeparatorComponent={() => <View style={styles.commentGap} />}
              keyExtractor={(item) => item.id}
              ListEmptyComponent={(
                <Text style={styles.emptyComments}>暂时还没有评论</Text>
              )}
              ListHeaderComponent={header}
              renderItem={({ item }) => <CommentRow comment={item} />}
              removeClippedSubviews
              windowSize={5}
            />
            <View style={styles.interactionDock}>
              <TextInput
                onChangeText={setCommentText}
                onSubmitEditing={() => void submitComment()}
                placeholder="平等表达，友善交流"
                placeholderTextColor={colors.muted}
                returnKeyType="send"
                style={styles.commentInput}
                value={commentText}
              />
              {commentText.trim() ? (
                <Pressable
                  accessibilityLabel="发送评论"
                  disabled={submitting}
                  hitSlop={6}
                  onPress={() => void submitComment()}
                  style={styles.dockAction}
                >
                  {submitting ? (
                    <ActivityIndicator color={colors.accent} size="small" />
                  ) : (
                    <Send color={colors.accentDark} size={20} />
                  )}
                </Pressable>
              ) : null}
              <Pressable
                accessibilityLabel="点赞"
                hitSlop={6}
                onPress={() => void like()}
                style={styles.dockAction}
              >
                <Heart
                  color={article.liked ? colors.accentDark : colors.muted}
                  fill={article.liked ? colors.accentDark : "transparent"}
                  size={21}
                />
              </Pressable>
              <Pressable
                accessibilityLabel="分享"
                hitSlop={6}
                onPress={share}
                style={styles.dockAction}
              >
                <Send color={colors.muted} size={20} />
              </Pressable>
            </View>
          </>
        )}
      </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function ArticleContent({ article }: { article: CommunityArticle }) {
  const official = article.identity_badge?.code === "official";
  const body = removeCommunityEmoji(article.body_text);
  return (
    <>
      <View style={styles.article}>
        <View style={styles.articleTypeRow}>
          <View style={styles.typeBadge}>
            <Text style={styles.typeLabel}>{article.article_type_label}</Text>
          </View>
          {article.qa_status ? (
            <Text style={styles.qaStatus}>
              {article.qa_status === "solved" ? "已解决" : "待回答"}
            </Text>
          ) : null}
        </View>
        <Text style={styles.articleTitle}>
          {normalizeCommunityText(article.title)}
        </Text>
        <View style={styles.authorRow}>
          <CommunityAvatar
            name={article.author_name}
            size={38}
            uri={article.author_avatar_url}
            verified={official}
          />
          <View style={styles.authorCopy}>
            <View style={styles.authorNameRow}>
              <Text numberOfLines={1} style={styles.authorName}>
                {article.author_name || "社区用户"}
              </Text>
              {article.identity_badge ? (
                <BadgeCheck color={colors.accent} size={14} />
              ) : null}
            </View>
            <Text style={styles.authorMeta}>
              {formatCommunityDate(article.published_at)}
            </Text>
          </View>
        </View>
        {article.cover_url ? (
          <Image
            resizeMode="cover"
            source={{ uri: article.cover_url }}
            style={styles.cover}
          />
        ) : null}
        <Text selectable style={styles.bodyText}>{body}</Text>
        {article.tags.length ? (
          <View style={styles.tags}>
            {article.tags.map((tag) => (
              <Text key={tag} style={styles.tag}>
                #{normalizeCommunityText(tag)}
              </Text>
            ))}
          </View>
        ) : null}
        <View style={styles.stats}>
          <Stat icon={Eye} label={`${article.view_count} 浏览`} />
          <Stat icon={Heart} label={`${article.like_count} 点赞`} />
          <Stat icon={MessageCircle} label={`${article.comment_count} 评论`} />
        </View>
      </View>
      <View style={styles.commentsHeader}>
        <Text style={styles.commentsTitle}>全部评论</Text>
        <Text style={styles.commentsCount}>{article.comment_count}</Text>
      </View>
    </>
  );
}

function Stat({
  icon: Icon,
  label,
}: {
  icon: typeof Eye;
  label: string;
}) {
  return (
    <View style={styles.stat}>
      <Icon color={colors.faint} size={14} />
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function CommentRow({
  comment,
  nested = false,
}: {
  comment: CommunityComment;
  nested?: boolean;
}) {
  return (
    <View style={[styles.comment, nested && styles.nestedComment]}>
      <CommunityAvatar
        name={comment.author_name}
        size={nested ? 28 : 34}
        uri={comment.author_avatar_url}
        verified={comment.identity_badge?.code === "official"}
      />
      <View style={styles.commentCopy}>
        <View style={styles.commentNameRow}>
          <Text style={styles.commentName}>{comment.author_name || "社区用户"}</Text>
          {comment.accepted ? <Text style={styles.accepted}>已采纳</Text> : null}
        </View>
        <Text style={styles.commentBody}>
          {removeCommunityEmoji(comment.content)}
        </Text>
        <Text style={styles.commentMeta}>
          {formatCommunityDate(comment.created_at)} · {comment.like_count} 赞
        </Text>
        {comment.replies.map((reply) => (
          <CommentRow comment={reply} key={reply.id} nested />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  flex: { flex: 1 },
  shell: { flex: 1, width: "100%", maxWidth: 760, alignSelf: "center" },
  header: {
    height: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
    backgroundColor: colors.surface,
  },
  headerAction: {
    width: 52,
    height: 52,
    alignItems: "center",
    justifyContent: "center",
  },
  headerTitle: {
    flex: 1,
    color: colors.ink,
    fontSize: 17,
    fontWeight: "600",
    textAlign: "center",
  },
  list: { paddingBottom: 78 },
  article: { padding: spacing.md, backgroundColor: colors.surface },
  articleTypeRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  typeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.accentSoft,
  },
  typeLabel: { color: colors.accentDark, fontSize: 10, fontWeight: "600" },
  qaStatus: { color: colors.accentDark, fontSize: 11 },
  articleTitle: {
    marginTop: 12,
    color: colors.ink,
    fontSize: 25,
    fontWeight: "700",
    lineHeight: 34,
    letterSpacing: -0.55,
  },
  authorRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginTop: spacing.md,
  },
  authorCopy: { flex: 1, minWidth: 0, gap: 2 },
  authorNameRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  authorName: { flexShrink: 1, color: colors.ink, fontSize: 13, fontWeight: "600" },
  authorMeta: { color: colors.faint, fontSize: 10 },
  cover: {
    width: "100%",
    aspectRatio: 1.65,
    marginTop: spacing.md,
    borderRadius: 14,
    backgroundColor: colors.groupedBackground,
  },
  bodyText: {
    marginTop: spacing.lg,
    color: colors.ink,
    fontSize: 15,
    lineHeight: 25,
  },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.lg },
  tag: {
    paddingHorizontal: 8,
    paddingVertical: 5,
    overflow: "hidden",
    borderRadius: 8,
    color: colors.accentDark,
    backgroundColor: colors.accentSoft,
    fontSize: 11,
  },
  stats: {
    flexDirection: "row",
    gap: 18,
    marginTop: spacing.lg,
    paddingTop: 14,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  stat: { flexDirection: "row", alignItems: "center", gap: 5 },
  statLabel: { color: colors.faint, fontSize: 11 },
  commentsHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 8,
    padding: spacing.md,
    backgroundColor: colors.surface,
  },
  commentsTitle: { color: colors.ink, fontSize: 15, fontWeight: "600" },
  commentsCount: { color: colors.faint, fontSize: 12 },
  comment: {
    flexDirection: "row",
    gap: 10,
    paddingHorizontal: spacing.md,
    paddingVertical: 13,
    backgroundColor: colors.surface,
  },
  nestedComment: {
    marginTop: 12,
    paddingHorizontal: 0,
    paddingVertical: 0,
    backgroundColor: "transparent",
  },
  commentCopy: { flex: 1, minWidth: 0 },
  commentNameRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  commentName: { color: colors.ink, fontSize: 12, fontWeight: "600" },
  accepted: {
    paddingHorizontal: 5,
    paddingVertical: 2,
    overflow: "hidden",
    borderRadius: 5,
    color: colors.white,
    backgroundColor: colors.accent,
    fontSize: 9,
  },
  commentBody: { marginTop: 5, color: colors.ink, fontSize: 13, lineHeight: 20 },
  commentMeta: { marginTop: 5, color: colors.faint, fontSize: 10 },
  commentGap: { height: StyleSheet.hairlineWidth, backgroundColor: colors.line },
  emptyComments: {
    padding: spacing.xl,
    color: colors.muted,
    backgroundColor: colors.surface,
    textAlign: "center",
  },
  interactionDock: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    minHeight: 62,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.hairline,
    backgroundColor: colors.tabBar,
  },
  commentInput: {
    flex: 1,
    height: 39,
    paddingHorizontal: 13,
    borderRadius: 12,
    color: colors.ink,
    backgroundColor: colors.searchBackground,
    fontSize: 13,
  },
  dockAction: { width: 38, height: 38, alignItems: "center", justifyContent: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  stateTitle: { marginTop: 12, color: colors.ink, fontSize: 17, fontWeight: "600" },
  stateCopy: { marginTop: 7, color: colors.muted, fontSize: 13, textAlign: "center" },
  retry: {
    minWidth: 108,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.md,
    borderRadius: radius.sm,
    backgroundColor: colors.accent,
  },
  retryLabel: { color: colors.white, fontSize: 13, fontWeight: "600" },
});
