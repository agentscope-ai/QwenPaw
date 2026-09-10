import { router } from "expo-router";
import {
  RefreshCw,
  SquarePen,
} from "lucide-react-native";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getPlatformAccessToken } from "../../api/platform";
import { IosHeader } from "../../components/IosHeader";
import { MobileAlert } from "../../components/MobileAlert";
import { MobileToast } from "../../components/MobileToast";
import {
  communityArticleUrl,
  getCommunityMeta,
  likeCommunityArticle,
  listCommunityArticles,
} from "../../features/community/api";
import { CommunityPostCard } from "../../features/community/components/CommunityPostCard";
import type {
  CommunityArticleSummary,
  CommunityArticleType,
  CommunitySort,
} from "../../features/community/types";
import { mobileText } from "../../i18n/locale";
import { qwenPawBrandAssets } from "../../theme/brandAssets";
import { colors, radius, spacing } from "../../theme/tokens";

const PAGE_SIZE = 12;

export default function CommunityScreen() {
  const [articles, setArticles] = useState<CommunityArticleSummary[]>([]);
  const [types, setTypes] = useState<CommunityArticleType[]>([]);
  const [selectedType, setSelectedType] = useState("");
  const [sort, setSort] = useState<CommunitySort>("recommended");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const requestVersion = useRef(0);

  useEffect(() => {
    void getCommunityMeta()
      .then((meta) => setTypes(meta.filter_types))
      .catch(() => undefined);
  }, []);

  const loadFirstPage = useCallback(async (refresh = false) => {
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const result = await listCommunityArticles({
        page: 1,
        pageSize: PAGE_SIZE,
        sort,
        type: selectedType || undefined,
      });
      if (version !== requestVersion.current) return;
      setArticles(result.items);
      setPage(1);
      setHasMore(result.items.length < result.total);
    } catch (caught) {
      if (version !== requestVersion.current) return;
      setArticles([]);
      setError(caught instanceof Error ? caught.message : "社区加载失败");
    } finally {
      if (version === requestVersion.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [selectedType, sort]);

  useEffect(() => {
    const timer = setTimeout(() => void loadFirstPage(), 0);
    return () => clearTimeout(timer);
  }, [loadFirstPage]);

  const loadMore = useCallback(async () => {
    if (!hasMore || loading || loadingMore || refreshing) return;
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const result = await listCommunityArticles({
        page: nextPage,
        pageSize: PAGE_SIZE,
        sort,
        type: selectedType || undefined,
      });
      setArticles((current) => {
        const known = new Set(current.map((article) => article.id));
        return [
          ...current,
          ...result.items.filter((article) => !known.has(article.id)),
        ];
      });
      setPage(nextPage);
      setHasMore(nextPage * PAGE_SIZE < result.total);
    } catch {
      setHasMore(false);
    } finally {
      setLoadingMore(false);
    }
  }, [hasMore, loading, loadingMore, page, refreshing, selectedType, sort]);

  const openArticle = useCallback((articleId: string) => {
    router.push({
      pathname: "/community/[id]",
      params: { id: articleId },
    });
  }, []);

  const shareArticle = useCallback((article: CommunityArticleSummary) => {
    void Share.share({
      message: `${article.title}\n${communityArticleUrl(article.id)}`,
      url: communityArticleUrl(article.id),
    });
  }, []);

  const openComposer = useCallback(async () => {
    const token = await getPlatformAccessToken();
    if (token) {
      router.push("/community/compose");
      return;
    }
    router.push({
      pathname: "/community/login",
      params: { returnTo: "compose" },
    });
  }, []);

  const interactArticle = useCallback(async (
    article: CommunityArticleSummary,
  ) => {
    const token = await getPlatformAccessToken();
    if (!token) {
      MobileAlert.alert(
        "登录后点赞",
        "登录 AgentScope Platform 后，操作会实时同步到社区。",
        [
          { text: "取消", style: "cancel" },
          {
            text: "登录",
            onPress: () => router.push("/community/login"),
          },
        ],
      );
      return;
    }
    try {
      const updated = await likeCommunityArticle(article.id);
      setArticles((current) => current.map((item) => item.id === article.id
        ? {
          ...item,
          liked: updated.liked,
          like_count: updated.like_count,
        }
        : item));
    } catch (caught) {
      setToast(caught instanceof Error ? caught.message : "点赞失败，请稍后重试");
    }
  }, []);

  const renderArticle = useCallback(({
    item,
  }: {
    item: CommunityArticleSummary;
  }) => (
    <CommunityPostCard
      article={item}
      onInteract={() => void interactArticle(item)}
      onOpen={() => openArticle(item.id)}
      onShare={() => shareArticle(item)}
    />
  ), [interactArticle, openArticle, shareArticle]);

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <View style={styles.shell}>
        <IosHeader
          actionIcon={SquarePen}
          actionLabel={mobileText("发布社区文章", "Create post")}
          emphasizedAction
          onAction={() => void openComposer()}
          title={mobileText("社区", "Community")}
        />
        <View style={styles.sortTabs}>
          <SortButton
            active={sort === "recommended"}
            label={mobileText("推荐", "Recommended")}
            onPress={() => setSort("recommended")}
          />
          <SortButton
            active={sort === "latest"}
            label={mobileText("最新", "Latest")}
            onPress={() => setSort("latest")}
          />
        </View>
        <View style={styles.categoryBar}>
          <FlatList
            contentContainerStyle={styles.categoryContent}
            data={[{ code: "", label: mobileText("全部", "All") }, ...types]}
            horizontal
            keyExtractor={(item) => item.code || "all"}
            renderItem={({ item }) => (
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ selected: selectedType === item.code }}
                onPress={() => setSelectedType(item.code)}
                style={[
                  styles.category,
                  selectedType === item.code && styles.activeCategory,
                ]}
              >
                <Text
                  maxFontSizeMultiplier={1.25}
                  style={[
                    styles.categoryLabel,
                    selectedType === item.code && styles.activeCategoryLabel,
                  ]}
                >
                  {item.label}
                </Text>
              </Pressable>
            )}
            showsHorizontalScrollIndicator={false}
          />
        </View>

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.accent} />
            <Text maxFontSizeMultiplier={1.35} style={styles.stateCopy}>
              {mobileText("正在读取 Platform 社区", "Loading Platform Community")}
            </Text>
          </View>
        ) : error ? (
          <View style={styles.center}>
            <View style={styles.stateIcon}>
              <RefreshCw color={colors.accent} size={25} />
            </View>
            <Text maxFontSizeMultiplier={1.4} style={styles.stateTitle}>
              {mobileText("暂时无法加载社区", "Community is unavailable")}
            </Text>
            <Text maxFontSizeMultiplier={1.35} style={styles.stateCopy}>
              {error}
            </Text>
            <Pressable
              onPress={() => void loadFirstPage()}
              style={styles.retry}
            >
              <Text maxFontSizeMultiplier={1.25} style={styles.retryLabel}>
                {mobileText("重新加载", "Reload")}
              </Text>
            </Pressable>
          </View>
        ) : (
          <FlatList
            contentContainerStyle={articles.length ? styles.list : styles.emptyList}
            data={articles}
            ItemSeparatorComponent={() => <View style={styles.separator} />}
            keyExtractor={(item) => item.id}
            ListEmptyComponent={(
              <View style={styles.center}>
                <Image
                  accessible={false}
                  resizeMode="contain"
                  source={qwenPawBrandAssets.paw}
                  style={styles.emptyImage}
                />
                <Text maxFontSizeMultiplier={1.4} style={styles.stateTitle}>
                  {mobileText("这个分类还没有内容", "No posts in this category")}
                </Text>
                <Text maxFontSizeMultiplier={1.35} style={styles.stateCopy}>
                  {mobileText(
                    "换个分类看看，或者发布第一篇内容。",
                    "Try another category or publish the first post.",
                  )}
                </Text>
              </View>
            )}
            ListFooterComponent={loadingMore ? (
              <ActivityIndicator color={colors.accent} style={styles.footer} />
            ) : null}
            onEndReached={() => void loadMore()}
            onEndReachedThreshold={0.45}
            refreshControl={(
              <RefreshControl
                onRefresh={() => void loadFirstPage(true)}
                refreshing={refreshing}
                tintColor={colors.accent}
              />
            )}
            removeClippedSubviews
            renderItem={renderArticle}
            windowSize={7}
          />
        )}
        <MobileToast message={toast} onHide={() => setToast(null)} />
      </View>
    </SafeAreaView>
  );
}

function SortButton({
  active,
  label,
  onPress,
}: {
  active: boolean;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={[styles.sortButton, active && styles.activeSortButton]}
    >
      <Text
        maxFontSizeMultiplier={1.3}
        style={[styles.sortLabel, active && styles.activeSortLabel]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  shell: { flex: 1, width: "100%", maxWidth: 760, alignSelf: "center" },
  sortTabs: {
    height: 52,
    flexDirection: "row",
    gap: 4,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    padding: 4,
    borderRadius: radius.sm,
    backgroundColor: colors.searchBackground,
  },
  sortButton: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
  },
  activeSortButton: { backgroundColor: colors.surfaceStrong },
  sortLabel: { color: colors.muted, fontSize: 14 },
  activeSortLabel: { color: colors.ink, fontWeight: "600" },
  categoryBar: {
    paddingBottom: spacing.sm,
    backgroundColor: colors.groupedBackground,
  },
  categoryContent: { gap: 7, paddingHorizontal: spacing.md },
  category: {
    height: 44,
    justifyContent: "center",
    paddingHorizontal: 13,
    borderRadius: radius.pill,
    backgroundColor: colors.groupedBackground,
  },
  activeCategory: { backgroundColor: colors.accentSoft },
  categoryLabel: { color: colors.muted, fontSize: 12 },
  activeCategoryLabel: { color: colors.accentDark, fontWeight: "600" },
  list: { paddingBottom: spacing.lg },
  emptyList: { flexGrow: 1 },
  separator: { height: 12 },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    paddingBottom: 80,
  },
  stateIcon: {
    width: 54,
    height: 54,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.md,
    borderRadius: 17,
    backgroundColor: colors.accentSoft,
  },
  stateTitle: {
    marginTop: spacing.sm,
    color: colors.ink,
    fontSize: 17,
    fontWeight: "600",
    textAlign: "center",
  },
  stateCopy: {
    marginTop: spacing.xs,
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
  },
  retry: {
    minWidth: 108,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.md,
    borderRadius: radius.sm,
    backgroundColor: colors.accent,
  },
  retryLabel: { color: colors.white, fontSize: 13, fontWeight: "600" },
  emptyImage: { width: 60, height: 58, marginBottom: spacing.xs },
  footer: { paddingVertical: spacing.lg },
});
