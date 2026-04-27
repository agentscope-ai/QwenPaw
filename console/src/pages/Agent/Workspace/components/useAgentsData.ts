import { useState, useEffect } from "react";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type { MarkdownFile, DailyMemoryFile } from "../../../../api/types";
import { workspaceApi } from "../../../../api/modules/workspace";
import { useAgentStore } from "../../../../stores/agentStore";

// Returns the parent directory of a file path, supporting both '/' and '\' separators.
const getParentDir = (filePath: string): string => {
  const match = filePath.match(/^(.*)[/\\]/);
  return match ? match[1] : filePath;
};

export const useAgentsData = () => {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [files, setFiles] = useState<MarkdownFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<MarkdownFile | null>(null);
  const [dailyMemories, setDailyMemories] = useState<DailyMemoryFile[]>([]);
  const [expandedMemory, setExpandedMemory] = useState(false);
  const [fileContent, setFileContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);
  const [enabledFiles, setEnabledFiles] = useState<string[]>([]);
  const { message } = useAppMessage();

  useEffect(() => {
    const initializeData = async () => {
      // Remember currently selected file name
      const previouslySelectedFilename = selectedFile?.filename;

      // Clear content first
      setFileContent("");
      setOriginalContent("");
      setExpandedMemory(false);

      const enabled = await fetchEnabledFiles();
      const fileList = await workspaceApi.listFiles();
      const sortedFiles = sortFilesByEnabled(
        fileList as unknown as MarkdownFile[],
        enabled,
      );
      setFiles(sortedFiles);

      // Set workspace path (handle both Unix '/' and Windows '\' separators)
      if (fileList.length > 0) {
        setWorkspacePath(getParentDir(fileList[0].path));
      } else {
        setWorkspacePath("");
      }

      // Try to re-select the same file in new workspace
      if (previouslySelectedFilename) {
        const sameFile = sortedFiles.find(
          (f) => f.filename === previouslySelectedFilename,
        );
        if (sameFile) {
          // Auto-load the same file from new workspace
          await handleFileClick(sameFile);
        } else {
          // File doesn't exist in new workspace, clear selection
          setSelectedFile(null);
        }
      } else {
        setSelectedFile(null);
      }
    };
    initializeData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgent]);

  // Re-sort when enabledFiles changes (for toggle/reorder operations)
  useEffect(() => {
    if (files.length > 0 && enabledFiles.length >= 0) {
      const sortedFiles = sortFilesByEnabled(files, enabledFiles);

      // Only update if order actually changed to avoid infinite loop
      const orderChanged = sortedFiles.some(
        (file, index) => file.filename !== files[index]?.filename,
      );
      if (orderChanged) {
        setFiles(sortedFiles);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabledFiles]);

  const fetchEnabledFiles = async () => {
    try {
      const result = await workspaceApi.getSystemPromptFiles();
      const enabled = Array.isArray(result) ? result : [];
      setEnabledFiles(enabled);
      return enabled;
    } catch (error) {
      console.error("Failed to fetch enabled files", error);
      return [];
    }
  };

  const sortFilesByEnabled = (
    fileList: MarkdownFile[],
    currentEnabledFiles: string[],
  ) => {
    const safeEnabled = Array.isArray(currentEnabledFiles)
      ? currentEnabledFiles
      : [];
    return [...fileList].sort((a, b) => {
      const aIndex = safeEnabled.indexOf(a.filename);
      const bIndex = safeEnabled.indexOf(b.filename);
      const aEnabled = aIndex !== -1;
      const bEnabled = bIndex !== -1;

      if (aEnabled && bEnabled) {
        return aIndex - bIndex;
      }
      if (aEnabled) return -1;
      if (bEnabled) return 1;
      return a.filename.localeCompare(b.filename);
    });
  };

  const fetchFiles = async (latestEnabledFiles?: string[]) => {
    try {
      // Validate with Array.isArray: onClick handlers may pass a MouseEvent as the first argument
      const enabled = Array.isArray(latestEnabledFiles)
        ? latestEnabledFiles
        : await fetchEnabledFiles();
      const fileList = await workspaceApi.listFiles();
      const sortedFiles = sortFilesByEnabled(
        fileList as unknown as MarkdownFile[],
        enabled,
      );
      setFiles(sortedFiles);
      // Set workspace path (handle both Unix '/' and Windows '\' separators)
      if (fileList.length > 0) {
        setWorkspacePath(getParentDir(fileList[0].path));
      } else {
        setWorkspacePath("");
      }
    } catch (error) {
      console.error("Failed to fetch files", error);
      message.error("Failed to load file list");
    }
  };

  const fetchDailyMemories = async () => {
    try {
      const memoryList = await api.listDailyMemory();
      setDailyMemories(memoryList);
    } catch (error) {
      console.error("Failed to fetch daily memories", error);
      message.error("Failed to load memory list");
    }
  };

  const handleFileClick = async (file: MarkdownFile) => {
    if (file.filename === "MEMORY.md") {
      if (expandedMemory && selectedFile?.filename === "MEMORY.md") {
        setExpandedMemory(false);
        return;
      } else {
        setExpandedMemory(true);
        fetchDailyMemories();
      }
    }

    setSelectedFile(file);
    setLoading(true);
    try {
      const data = await workspaceApi.loadFile(file.filename);
      setFileContent(data.content);
      setOriginalContent(data.content);
    } catch (error) {
      console.error("Failed to load file", error);
      message.error("Failed to load file");
    } finally {
      setLoading(false);
    }
  };

  const handleDailyMemoryClick = async (daily: DailyMemoryFile) => {
    setSelectedFile({
      filename: `${daily.date}.md`,
      path: daily.path,
      size: daily.size,
      created_time: daily.created_time,
      modified_time: daily.modified_time,
      updated_at: daily.updated_at,
    });
    setLoading(true);
    try {
      const data = await api.loadDailyMemory(daily.date);
      setFileContent(data.content);
      setOriginalContent(data.content);
    } catch (error) {
      console.error("Failed to load daily memory", error);
      message.error("Failed to load daily memory");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!selectedFile) return;
    setLoading(true);
    try {
      if (selectedFile.filename.match(/^\d{4}-\d{2}-\d{2}\.md$/)) {
        const date = selectedFile.filename.replace(".md", "");
        await api.saveDailyMemory(date, fileContent);
      } else {
        await api.saveFile(selectedFile.filename, fileContent);
      }
      setOriginalContent(fileContent);
      message.success("Saved successfully");
      if (selectedFile.filename.match(/^\d{4}-\d{2}-\d{2}\.md$/)) {
        fetchDailyMemories();
      } else {
        fetchFiles();
      }
    } catch (error) {
      console.error("Failed to save file", error);
      message.error("Failed to save");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFileContent(originalContent);
  };

  const handleToggleFileEnabled = async (filename: string) => {
    const isEnabling = !enabledFiles.includes(filename);

    // Show warning for MEMORY.md
    if (isEnabling && filename === "MEMORY.md") {
      message.warning({
        content: t("workspace.memoryFileWarning"),
        duration: 5,
      });
    }

    const newEnabledFiles = enabledFiles.includes(filename)
      ? enabledFiles.filter((f) => f !== filename)
      : [...enabledFiles, filename];

    try {
      await workspaceApi.setSystemPromptFiles(newEnabledFiles);
      setEnabledFiles(newEnabledFiles);
      message.success(
        t("workspace.configUpdated") || "System prompt configuration updated",
      );
    } catch (error) {
      console.error("Failed to update system prompt files", error);
      message.error(
        t("workspace.configUpdateFailed") ||
          "Failed to update system prompt configuration",
      );
    }
  };

  const handleReorderFiles = async (newOrder: string[]) => {
    try {
      await workspaceApi.setSystemPromptFiles(newOrder);
      setEnabledFiles(newOrder);
    } catch (error) {
      console.error("Failed to reorder files", error);
      message.error("Failed to update file order");
    }
  };

  const hasChanges = fileContent !== originalContent;

  return {
    files,
    selectedFile,
    dailyMemories,
    expandedMemory,
    fileContent,
    loading,
    workspacePath,
    hasChanges,
    enabledFiles,
    setFileContent,
    fetchFiles,
    fetchDailyMemories,
    handleFileClick,
    handleDailyMemoryClick,
    handleSave,
    handleReset,
    handleToggleFileEnabled,
    handleReorderFiles,
  };
};
