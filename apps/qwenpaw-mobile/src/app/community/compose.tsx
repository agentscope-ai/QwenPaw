import { MobileAlert } from "@/components/MobileAlert";
import { router } from "expo-router";
import { ChevronLeft, ShieldCheck } from "lucide-react-native";
import { useEffect, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getPlatformAccessToken } from "../../api/platform";
import {
  getCommunityMeta,
  publishCommunityArticle,
} from "../../features/community/api";
import type { CommunityArticleType } from "../../features/community/types";
import { colors, radius, spacing } from "../../theme/tokens";

export default function CommunityComposeScreen() {
  const [types, setTypes] = useState<CommunityArticleType[]>([]);
  const [articleType, setArticleType] = useState("work_share");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    void getPlatformAccessToken().then((token) => {
      if (!token) {
        router.replace({
          pathname: "/community/login",
          params: { returnTo: "compose" },
        });
      }
    });
    void getCommunityMeta().then((meta) => {
      setTypes(meta.article_types);
      if (meta.article_types[0]) setArticleType(meta.article_types[0].code);
    }).catch(() => undefined);
  }, []);

  const publish = async () => {
    if (!title.trim()) {
      MobileAlert.alert("请输入标题");
      return;
    }
    if (!body.trim()) {
      MobileAlert.alert("请输入正文");
      return;
    }
    MobileAlert.alert(
      "发布到公开社区？",
      "这篇文章会立即同步到 AgentScope Platform，所有社区用户均可查看。",
      [
        { text: "取消", style: "cancel" },
        {
          text: "确认发布",
          onPress: () => void submitPublish(),
        },
      ],
    );
  };

  const submitPublish = async () => {
    setPublishing(true);
    try {
      const article = await publishCommunityArticle({
        title,
        body,
        articleType,
        tags: tags.split(/[,，\s]+/).filter(Boolean),
      });
      router.replace({
        pathname: "/community/[id]",
        params: { id: article.id },
      });
    } catch (caught) {
      MobileAlert.alert(
        "发布失败",
        caught instanceof Error ? caught.message : "请稍后重试",
      );
    } finally {
      setPublishing(false);
    }
  };

  return (
    <SafeAreaView edges={["top", "bottom"]} style={styles.root}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        <View style={styles.header}>
          <Pressable
            accessibilityLabel="返回"
            hitSlop={8}
            onPress={() => router.back()}
            style={styles.headerAction}
          >
            <ChevronLeft color={colors.ink} size={25} />
          </Pressable>
          <Text style={styles.headerTitle}>发布文章</Text>
          <Pressable
            disabled={publishing}
            onPress={() => void publish()}
            style={styles.publishAction}
          >
            <Text style={styles.publishLabel}>
              {publishing ? "发布中" : "发布"}
            </Text>
          </Pressable>
        </View>
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.fieldLabel}>文章类型</Text>
          <ScrollView
            contentContainerStyle={styles.typeContent}
            horizontal
            showsHorizontalScrollIndicator={false}
          >
            {(types.length ? types : fallbackTypes).map((type) => (
              <Pressable
                key={type.code}
                onPress={() => setArticleType(type.code)}
                style={[
                  styles.typeChip,
                  articleType === type.code && styles.activeTypeChip,
                ]}
              >
                <Text style={[
                  styles.typeLabel,
                  articleType === type.code && styles.activeTypeLabel,
                ]}>
                  {type.label}
                </Text>
              </Pressable>
            ))}
          </ScrollView>

          <TextInput
            maxLength={256}
            onChangeText={setTitle}
            placeholder="输入文章标题"
            placeholderTextColor={colors.faint}
            style={styles.titleInput}
            value={title}
          />
          <View style={styles.divider} />
          <TextInput
            multiline
            onChangeText={setBody}
            placeholder="分享你的 QwenPaw 实践、教程、案例或想法…"
            placeholderTextColor={colors.faint}
            style={styles.bodyInput}
            textAlignVertical="top"
            value={body}
          />
          <View style={styles.tagsField}>
            <Text style={styles.fieldLabel}>标签</Text>
            <TextInput
              autoCapitalize="none"
              onChangeText={setTags}
              placeholder="用空格或逗号分隔，最多 5 个"
              placeholderTextColor={colors.faint}
              style={styles.tagsInput}
              value={tags}
            />
          </View>
          <View style={styles.privacyNote}>
            <ShieldCheck color={colors.accentDark} size={17} />
            <Text style={styles.privacyCopy}>
              只会发布当前填写的标题、正文和标签，不会读取或附带会话、记忆、密钥、环境变量及本地路径。
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const fallbackTypes: CommunityArticleType[] = [
  { code: "work_share", label: "开发分享" },
  { code: "app_case", label: "应用案例" },
  { code: "beginner_tutorial", label: "新手教程" },
  { code: "discussion", label: "交流讨论" },
];

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  header: {
    height: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
  },
  headerAction: { width: 52, height: 52, alignItems: "center", justifyContent: "center" },
  headerTitle: { flex: 1, color: colors.ink, fontSize: 17, fontWeight: "600", textAlign: "center" },
  publishAction: { minWidth: 58, height: 52, alignItems: "center", justifyContent: "center" },
  publishLabel: { color: colors.accentDark, fontSize: 15, fontWeight: "600" },
  content: {
    width: "100%",
    maxWidth: 760,
    minHeight: "100%",
    alignSelf: "center",
    padding: spacing.md,
  },
  fieldLabel: { color: colors.muted, fontSize: 12, fontWeight: "500" },
  typeContent: { gap: 7, paddingVertical: 10 },
  typeChip: {
    height: 32,
    justifyContent: "center",
    paddingHorizontal: 12,
    borderRadius: radius.pill,
    backgroundColor: colors.groupedBackground,
  },
  activeTypeChip: { backgroundColor: colors.accentSoft },
  typeLabel: { color: colors.muted, fontSize: 12 },
  activeTypeLabel: { color: colors.accentDark, fontWeight: "600" },
  titleInput: {
    minHeight: 58,
    color: colors.ink,
    fontSize: 21,
    fontWeight: "600",
    paddingVertical: 8,
  },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: colors.line },
  bodyInput: {
    minHeight: 260,
    color: colors.ink,
    fontSize: 15,
    lineHeight: 24,
    paddingTop: spacing.md,
  },
  tagsField: {
    gap: 8,
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  tagsInput: {
    height: 43,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    color: colors.ink,
    backgroundColor: colors.groupedBackground,
    fontSize: 13,
  },
  privacyNote: {
    flexDirection: "row",
    gap: 9,
    marginTop: spacing.lg,
    padding: 13,
    borderRadius: radius.md,
    backgroundColor: colors.accentSoft,
  },
  privacyCopy: { flex: 1, color: colors.muted, fontSize: 11, lineHeight: 17 },
});
