import {
  BadgeCheck,
  Eye,
  Heart,
  MessageCircle,
  Send,
} from "lucide-react-native";
import { memo } from "react";
import {
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors, radius, spacing } from "../../../theme/tokens";
import {
  formatCommunityDate,
  normalizeCommunityText,
} from "../model";
import type { CommunityArticleSummary } from "../types";
import { CommunityAvatar } from "./CommunityAvatar";

export const CommunityPostCard = memo(function CommunityPostCard({
  article,
  onInteract,
  onOpen,
  onShare,
}: {
  article: CommunityArticleSummary;
  onInteract: () => void;
  onOpen: () => void;
  onShare: () => void;
}) {
  const official = article.identity_badge?.code === "official";
  const summary = normalizeCommunityText(article.summary);

  return (
    <View style={styles.post}>
      <View style={styles.authorRow}>
        <CommunityAvatar
          name={article.author_name}
          uri={article.author_avatar_url}
          verified={official}
        />
        <View style={styles.authorCopy}>
          <View style={styles.authorNameRow}>
            <Text
              maxFontSizeMultiplier={1.3}
              numberOfLines={1}
              style={styles.authorName}
            >
              {article.author_name || "社区用户"}
            </Text>
            {article.identity_badge ? (
              <BadgeCheck
                accessibilityLabel="已认证"
                color={colors.accent}
                fill={colors.accentSoft}
                size={14}
              />
            ) : null}
          </View>
          <Text
            maxFontSizeMultiplier={1.25}
            numberOfLines={1}
            style={styles.authorMeta}
          >
            {formatCommunityDate(article.published_at)} · {article.article_type_label}
          </Text>
        </View>
        {article.is_featured ? (
          <View style={styles.featuredBadge}>
            <Text maxFontSizeMultiplier={1.2} style={styles.featuredLabel}>
              精选
            </Text>
          </View>
        ) : null}
      </View>

      <Pressable
        accessibilityRole="button"
        onPress={onOpen}
        style={({ pressed }) => [styles.body, pressed && styles.pressed]}
      >
        <Text maxFontSizeMultiplier={1.4} numberOfLines={3} style={styles.title}>
          {normalizeCommunityText(article.title)}
        </Text>
        {summary ? (
          <Text maxFontSizeMultiplier={1.35} numberOfLines={3} style={styles.summary}>
            {summary}
          </Text>
        ) : null}
        {article.cover_url ? (
          <Image
            accessibilityLabel={`${normalizeCommunityText(article.title)} 封面`}
            resizeMode="cover"
            source={{ uri: article.cover_url }}
            style={styles.cover}
          />
        ) : null}
        <MetaTags article={article} />
      </Pressable>

      <View style={styles.actions}>
        <PostAction
          accessibilityLabel={`点赞 ${article.like_count}`}
          active={article.liked}
          icon={Heart}
          label={String(article.like_count)}
          onPress={onInteract}
        />
        <PostAction
          accessibilityLabel={`评论 ${article.comment_count}`}
          icon={MessageCircle}
          label={String(article.comment_count)}
          onPress={onOpen}
        />
        <PostAction
          accessibilityLabel={`浏览 ${article.view_count}`}
          icon={Eye}
          label={String(article.view_count)}
          onPress={onOpen}
        />
        <PostAction
          accessibilityLabel="分享文章"
          icon={Send}
          label="分享"
          onPress={onShare}
        />
      </View>
    </View>
  );
});

function MetaTags({ article }: { article: CommunityArticleSummary }) {
  const tags = article.tags.slice(0, 3);
  const related = [
    article.related_skill_ids.length
      ? `${article.related_skill_ids.length} 个 Skill`
      : "",
    article.related_plugin_ids.length
      ? `${article.related_plugin_ids.length} 个 Plugin`
      : "",
  ].filter(Boolean);
  if (!tags.length && !related.length && !article.qa_status) return null;
  return (
    <View style={styles.tags}>
      {article.qa_status ? (
        <Text
          maxFontSizeMultiplier={1.2}
          style={[styles.tag, styles.statusTag]}
        >
          {article.qa_status === "solved" ? "已解决" : "待回答"}
        </Text>
      ) : null}
      {tags.map((tag) => (
        <Text maxFontSizeMultiplier={1.2} key={tag} style={styles.tag}>
          #{normalizeCommunityText(tag)}
        </Text>
      ))}
      {related.map((label) => (
        <Text
          maxFontSizeMultiplier={1.2}
          key={label}
          style={[styles.tag, styles.resourceTag]}
        >
          {label}
        </Text>
      ))}
    </View>
  );
}

function PostAction({
  accessibilityLabel,
  active = false,
  icon: Icon,
  label,
  onPress,
}: {
  accessibilityLabel: string;
  active?: boolean;
  icon: typeof Heart;
  label: string;
  onPress: () => void;
}) {
  const color = active ? colors.accentDark : colors.muted;
  return (
    <Pressable
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      hitSlop={4}
      onPress={onPress}
      style={({ pressed }) => [styles.action, pressed && styles.pressed]}
    >
      <Icon
        color={color}
        fill={active ? color : "transparent"}
        size={18}
        strokeWidth={1.8}
      />
      <Text
        maxFontSizeMultiplier={1.25}
        style={[styles.actionLabel, active && styles.activeAction]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  post: {
    marginHorizontal: spacing.md,
    paddingHorizontal: 15,
    paddingTop: 15,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  authorRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  authorCopy: { flex: 1, minWidth: 0, gap: 2 },
  authorNameRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  authorName: { flexShrink: 1, color: colors.ink, fontSize: 14, fontWeight: "600" },
  authorMeta: { color: colors.faint, fontSize: 11 },
  featuredBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.accentSoft,
  },
  featuredLabel: { color: colors.accentDark, fontSize: 10, fontWeight: "600" },
  body: { paddingTop: 12 },
  title: { color: colors.ink, fontSize: 17, fontWeight: "600", lineHeight: 24 },
  summary: { marginTop: 7, color: colors.muted, fontSize: 13, lineHeight: 20 },
  cover: {
    width: "100%",
    aspectRatio: 16 / 9,
    marginTop: 11,
    borderRadius: 15,
    backgroundColor: colors.groupedBackground,
  },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  tag: {
    paddingHorizontal: 7,
    paddingVertical: 4,
    overflow: "hidden",
    borderRadius: 7,
    color: colors.accentDark,
    backgroundColor: colors.accentSoft,
    fontSize: 10,
  },
  statusTag: { color: colors.white, backgroundColor: colors.accent },
  resourceTag: { color: colors.ink, backgroundColor: colors.searchBackground },
  actions: {
    minHeight: 44,
    flexDirection: "row",
    marginTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  action: {
    flex: 1,
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
  },
  actionLabel: { color: colors.muted, fontSize: 11 },
  activeAction: { color: colors.accentDark },
  pressed: { opacity: 0.48 },
});
