import * as DocumentPicker from "expo-document-picker";
import { File as LocalFile, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { ChevronLeft, File, FilePlus, FileText, Folder, Upload, X } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors, spacing } from "../../theme/tokens";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface DirectoryEntry {
  name: string;
  path: string;
  kind: "file" | "directory";
  size: number | null;
  preview_kind?: string;
}

interface DirectoryPage {
  directory: string;
  entries: DirectoryEntry[];
}

interface FileChunk {
  content: string;
  truncated?: boolean;
}

export function FilesSettings({ connection }: { connection: Connection }) {
  const [path, setPath] = useState("");
  const [page, setPage] = useState<DirectoryPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ name: string; content: string } | null>(null);
  const [editing, setEditing] = useState<{ path: string; name: string; content: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const query = new URLSearchParams({
        path,
        limit: "200",
        root: "workspace",
      });
      const value = await new QwenPawClient(connection)
        .inspectModule(`/workspace/tree?${query.toString()}`);
      setError(null);
      setPage(value as DirectoryPage);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection, path]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const shareFile = useCallback(async (entry: DirectoryEntry) => {
    setSaving(true);
    try {
      const query = new URLSearchParams({ path: entry.path, root: "workspace" });
      const data = await new QwenPawClient(connection).downloadModule(
        `/workspace/file-download?${query.toString()}`,
      );
      const safeName = entry.name.replace(/[/\\]/g, "-") || "qwenpaw-file";
      const file = new LocalFile(Paths.cache, safeName);
      file.create({ overwrite: true, intermediates: true });
      file.write(data.bytes);
      await Sharing.shareAsync(file.uri, { mimeType: data.contentType });
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }, [connection]);

  const open = useCallback(async (entry: DirectoryEntry) => {
    if (entry.kind === "directory") {
      setPath(entry.path);
      return;
    }
    if (entry.preview_kind && !["text", "csv"].includes(entry.preview_kind)) {
      await shareFile(entry);
      return;
    }
    try {
      const query = new URLSearchParams({
        path: entry.path,
        offset: "0",
        limit: String(256 * 1024),
        root: "workspace",
      });
      const chunk = await new QwenPawClient(connection)
        .inspectModule(`/workspace/file-content?${query.toString()}`) as FileChunk;
      if (chunk.truncated) {
        setPreview({
          name: entry.name,
          content: `${chunk.content ?? ""}\n\n[文件过大，仅显示前 256 KB，已禁用编辑]`,
        });
      } else {
        setEditing({ path: entry.path, name: entry.name, content: chunk.content ?? "" });
      }
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection, shareFile]);

  const goUp = () => {
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    setPath(parts.join("/"));
  };

  const upload = async () => {
    const result = await DocumentPicker.getDocumentAsync({ multiple: true });
    if (result.canceled) return;
    setSaving(true);
    try {
      const query = new URLSearchParams({ path, root: "workspace", conflict: "rename" });
      await new QwenPawClient(connection).uploadModule(
        `/workspace/file-upload?${query.toString()}`,
        result.assets.map((asset) => ({
          field: "files",
          uri: asset.uri,
          name: asset.name,
          mimeType: asset.mimeType,
        })),
      );
      await load();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  const createFile = () => {
    setEditing({ path: path ? `${path}/untitled.md` : "untitled.md", name: "新建文件", content: "" });
  };

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!page) return <ModuleLoading label={`正在读取 ${path || "工作空间"}…`} />;

  return (
    <>
      <IosGroup title={path || "工作空间根目录"}>
        {path ? (
          <IosRow icon={ChevronLeft} iconTone="ink" label="返回上一级" onPress={goUp} />
        ) : null}
        <IosRow
          icon={Upload}
          label={saving ? "正在上传…" : "上传文件"}
          onPress={saving ? undefined : () => void upload()}
          subtitle="同名文件会自动安全重命名"
        />
        <IosRow
          icon={FilePlus}
          iconTone="ink"
          label="新建文本文件"
          onPress={createFile}
          subtitle="保存时可指定相对路径"
        />
        {page.entries.map((entry) => (
          <IosRow
            icon={entry.kind === "directory" ? Folder : fileIcon(entry)}
            iconTone={entry.kind === "directory" ? "orange" : "ink"}
            key={entry.path}
            label={entry.name}
            onPress={() => void open(entry)}
            subtitle={entry.kind === "directory" ? "文件夹" : sizeLabel(entry.size)}
          />
        ))}
      </IosGroup>
      {!page.entries.length ? (
        <ModuleEmpty icon={Folder} title="空文件夹" subtitle="这里暂时没有文件。" />
      ) : null}
      <ModuleFooter>文件内容直接从当前 Agent workspace 读取，不经过 Platform 社区。</ModuleFooter>
      {preview ? (
        <Modal animationType="slide" presentationStyle="pageSheet">
          <SafeAreaView style={styles.previewRoot}>
            <View style={styles.previewHeader}>
              <Text numberOfLines={1} style={styles.previewTitle}>{preview.name}</Text>
              <Pressable accessibilityLabel="关闭预览" onPress={() => setPreview(null)}>
                <X color={colors.ink} size={22} />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={styles.previewContent}>
              <Text selectable style={styles.previewText}>{preview.content}</Text>
            </ScrollView>
          </SafeAreaView>
        </Modal>
      ) : null}
      {editing ? (
        <Modal animationType="slide" presentationStyle="pageSheet">
          <SafeAreaView style={styles.previewRoot}>
            <View style={styles.previewHeader}>
              <Pressable accessibilityLabel="取消编辑" onPress={() => setEditing(null)}>
                <X color={colors.ink} size={22} />
              </Pressable>
              <TextInput
                onChangeText={(next) => setEditing((current) => current ? { ...current, path: next } : null)}
                placeholder="相对路径"
                placeholderTextColor={colors.faint}
                style={styles.pathInput}
                value={editing.path}
              />
              <Pressable
                accessibilityLabel="保存文件"
                disabled={saving || !editing.path.trim()}
                onPress={() => void (async () => {
                  setSaving(true);
                  try {
                    const query = new URLSearchParams({
                      path: editing.path.trim(),
                      root: "workspace",
                    });
                    await new QwenPawClient(connection).mutateModule(
                      `/workspace/file-content?${query.toString()}`,
                      "PUT",
                      { content: editing.content },
                    );
                    setEditing(null);
                    setPreview(null);
                    await load();
                  } catch (reason) {
                    setError(errorMessage(reason));
                  } finally {
                    setSaving(false);
                  }
                })()}
              >
                <Text style={styles.saveText}>{saving ? "保存中" : "保存"}</Text>
              </Pressable>
            </View>
            <TextInput
              autoCapitalize="none"
              multiline
              onChangeText={(content) => setEditing((current) => current ? { ...current, content } : null)}
              placeholder="文件内容"
              placeholderTextColor={colors.faint}
              style={styles.editor}
              textAlignVertical="top"
              value={editing.content}
            />
          </SafeAreaView>
        </Modal>
      ) : null}
    </>
  );
}

function fileIcon(entry: DirectoryEntry) {
  return ["text", "csv"].includes(entry.preview_kind ?? "") ? FileText : File;
}

function sizeLabel(size: number | null): string {
  if (size === null) return "文件";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "读取失败";
}

const styles = StyleSheet.create({
  previewRoot: { flex: 1, backgroundColor: colors.groupedBackground },
  previewHeader: {
    height: 56,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
  },
  previewTitle: { flex: 1, color: colors.ink, fontSize: 17, fontWeight: "600" },
  pathInput: { flex: 1, color: colors.ink, fontSize: 15, paddingHorizontal: spacing.sm },
  saveText: { color: colors.accentDark, fontSize: 15, fontWeight: "600" },
  previewContent: { padding: spacing.md },
  previewText: {
    color: colors.ink,
    fontFamily: "Menlo",
    fontSize: 13,
    lineHeight: 20,
  },
  editor: {
    flex: 1,
    margin: spacing.md,
    padding: spacing.md,
    borderRadius: 12,
    color: colors.ink,
    backgroundColor: colors.surface,
    fontFamily: "Menlo",
    fontSize: 13,
    lineHeight: 20,
  },
});
