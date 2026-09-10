import { MobileAlert } from "@/components/MobileAlert";
import * as DocumentPicker from "expo-document-picker";
import {
  Check,
  Code2,
  FileDiff,
  FolderGit2,
  GitBranch,
  GitCommitHorizontal,
  Plus,
  RotateCcw,
  Upload,
} from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Switch } from "react-native";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { colors } from "../../theme/tokens";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleFooter, ModuleLoading } from "./ModuleState";

interface ProjectInfo {
  path: string;
  name: string;
  is_workspace_default: boolean;
}

interface ProjectListItem {
  path: string;
  name: string;
  is_git: boolean;
  is_active: boolean;
}

interface GitStatus {
  branch: string;
  changes: { path: string; status: string; staged: boolean }[];
  ahead: number;
  behind: number;
}

interface CommitInfo {
  hash: string;
  author: string;
  date: string;
  message: string;
}

export function ProjectGitSettings({ connection }: { connection: Connection }) {
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [coding, setCoding] = useState<boolean | null>(null);
  const [git, setGit] = useState<GitStatus | null>(null);
  const [commits, setCommits] = useState<CommitInfo[]>([]);
  const [editor, setEditor] = useState<
    "project" | "import" | "branch" | "commit" | null
  >(null);
  const [projectZip, setProjectZip] = useState<{
    uri: string;
    name: string;
    mimeType?: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const client = new QwenPawClient(connection);
    const [projectResult, listResult, codingResult, gitResult, logResult] =
      await Promise.allSettled([
        client.inspectModule("/workspace/project-directory"),
        client.inspectModule("/workspace/project-directory/list"),
        client.inspectModule("/coding-mode"),
        client.inspectModule("/workspace/git/status"),
        client.inspectModule("/workspace/git/log?limit=20"),
      ]);
    if (projectResult.status === "fulfilled") {
      setProject(projectResult.value as ProjectInfo);
    }
    if (listResult.status === "fulfilled") {
      setProjects(Array.isArray(listResult.value)
        ? listResult.value as ProjectListItem[]
        : []);
    }
    if (codingResult.status === "fulfilled") {
      setCoding((codingResult.value as { enabled?: boolean }).enabled === true);
    }
    setGit(gitResult.status === "fulfilled" ? gitResult.value as GitStatus : null);
    setCommits(logResult.status === "fulfilled" && Array.isArray(logResult.value)
      ? logResult.value as CommitInfo[]
      : []);
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const run = async (action: () => Promise<unknown>, success?: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      await load();
      if (success) MobileAlert.alert(success);
    } catch (reason) {
      MobileAlert.alert("操作失败", errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const uploadProject = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["application/zip", "application/octet-stream"],
    });
    if (result.canceled) return;
    const asset = result.assets[0];
    setProjectZip({
      uri: asset.uri,
      name: asset.name,
      mimeType: asset.mimeType,
    });
    setEditor("import");
  };

  if (project === null || projects === null || coding === null) {
    return <ModuleLoading />;
  }

  return (
    <>
      <IosGroup title="Coding 工作区">
        <IosRow
          accessory={(
            <Switch
              disabled={busy}
              onValueChange={(enabled) => void run(
                () => new QwenPawClient(connection).mutateModule(
                  "/coding-mode",
                  "POST",
                  { enabled },
                ),
              )}
              trackColor={{ false: colors.hairline, true: colors.accent }}
              value={coding}
            />
          )}
          icon={Code2}
          label="Coding Mode"
          subtitle="启用项目目录和代码工具"
        />
        <IosRow
          icon={FolderGit2}
          iconTone="ink"
          label={project.name || "Agent workspace"}
          subtitle={project.path}
          trailing={project.is_workspace_default ? "默认" : "当前"}
        />
        <IosRow
          icon={Plus}
          label="新建项目"
          onPress={busy ? undefined : () => setEditor("project")}
          subtitle="创建空目录并初始化 Git"
        />
        <IosRow
          icon={Upload}
          iconTone="ink"
          label="导入项目 ZIP"
          onPress={busy ? undefined : () => void uploadProject()}
        />
        {!project.is_workspace_default ? (
          <IosRow
            icon={RotateCcw}
            iconTone="ink"
            label="恢复默认 workspace"
            onPress={busy ? undefined : () => void run(
              () => new QwenPawClient(connection).mutateModule(
                "/workspace/project-directory",
                "PUT",
                { path: null },
              ),
            )}
          />
        ) : null}
      </IosGroup>

      {projects.length ? (
        <IosGroup title={`项目 · ${projects.length}`}>
          {projects.map((item) => (
            <IosRow
              icon={item.is_active ? Check : FolderGit2}
              iconTone={item.is_active ? "orange" : "ink"}
              key={item.path}
              label={item.name}
              onPress={item.is_active || busy ? undefined : () => void run(
                () => new QwenPawClient(connection).mutateModule(
                  "/workspace/project-directory",
                  "PUT",
                  { path: item.path },
                ),
              )}
              subtitle={item.is_git ? "Git 项目" : item.path}
              trailing={item.is_active ? "当前" : undefined}
            />
          ))}
        </IosGroup>
      ) : null}

      {git ? (
        <>
          <IosGroup title="Git">
            <IosRow
              icon={GitBranch}
              label={git.branch || "未命名分支"}
              onPress={busy ? undefined : () => setEditor("branch")}
              subtitle={`ahead ${git.ahead} · behind ${git.behind}`}
              trailing={`${git.changes.length} 项变更`}
            />
            <IosRow
              icon={GitCommitHorizontal}
              iconTone="ink"
              label="提交已暂存变更"
              onPress={busy ? undefined : () => setEditor("commit")}
              subtitle="填写提交说明后创建 Commit"
            />
            {git.changes.map((change) => (
              <IosRow
                icon={FileDiff}
                iconTone="ink"
                key={`${change.staged}:${change.path}`}
                label={change.path}
                onPress={() => openChange(change)}
                subtitle={change.status}
                trailing={change.staged ? "已暂存" : "未暂存"}
              />
            ))}
          </IosGroup>
          {commits.length ? (
            <IosGroup title="最近提交">
              {commits.map((commit) => (
                <IosRow
                  icon={GitCommitHorizontal}
                  iconTone="ink"
                  key={commit.hash}
                  label={commit.message}
                  onPress={() => openCommit(commit)}
                  subtitle={`${commit.author} · ${formatDate(commit.date)}`}
                  trailing={commit.hash.slice(0, 7)}
                />
              ))}
            </IosGroup>
          ) : null}
        </>
      ) : (
        <ModuleEmpty
          icon={GitBranch}
          title="当前目录不是 Git 项目"
          subtitle="新建或导入一个项目后即可管理分支与提交。"
        />
      )}

      <ModuleFooter>
        项目目录与 Git 操作直接作用于当前 Agent workspace，请确认变更后再提交或丢弃。
      </ModuleFooter>

      {editor ? (
        <DynamicConfigSheet
          fields={editor === "project" || editor === "import" ? [
            { name: "name", label: "项目名称", type: "text", required: true },
          ] : editor === "branch" ? [
            { name: "branch", label: "分支名称", type: "text", required: true },
            { name: "create", label: "创建新分支", type: "boolean" },
          ] : [
            { name: "message", label: "提交说明", type: "textarea", required: true },
          ]}
          onClose={() => setEditor(null)}
          onSave={async (values) => {
            const client = new QwenPawClient(connection);
            if (editor === "project") {
              await client.mutateModule(
                "/workspace/project-directory/create",
                "POST",
                { name: String(values.name).trim() },
              );
            } else if (editor === "import") {
              if (!projectZip) throw new Error("请重新选择项目 ZIP。");
              await client.uploadModule(
                `/workspace/project-directory/upload-zip?name=${encodeURIComponent(
                  String(values.name).trim(),
                )}`,
                [{ field: "file", ...projectZip }],
              );
              setProjectZip(null);
            } else if (editor === "branch") {
              await client.mutateModule("/workspace/git/checkout", "POST", {
                branch: String(values.branch).trim(),
                create: values.create === true,
              });
            } else {
              await client.mutateModule("/workspace/git/commit", "POST", {
                message: String(values.message).trim(),
              });
            }
            await load();
          }}
          title={editor === "project"
            ? "新建项目"
            : editor === "import"
              ? "导入项目 ZIP"
              : editor === "branch"
                ? "切换分支"
                : "创建 Commit"}
          values={editor === "import" ? {
            name: projectZip?.name.replace(/\.zip$/i, "") || "project",
          } : {}}
        />
      ) : null}
    </>
  );

  function openChange(change: GitStatus["changes"][number]) {
    MobileAlert.alert(change.path, change.status, [
      { text: "取消", style: "cancel" },
      {
        text: change.staged ? "取消暂存" : "暂存",
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          change.staged ? "/workspace/git/unstage" : "/workspace/git/stage",
          "POST",
          { paths: [change.path] },
        )),
      },
      ...(!change.staged ? [{
        text: "丢弃更改",
        style: "destructive" as const,
        onPress: () => void run(() => new QwenPawClient(connection).mutateModule(
          "/workspace/git/discard",
          "POST",
          { paths: [change.path] },
        )),
      }] : []),
    ]);
  }

  function openCommit(commit: CommitInfo) {
    MobileAlert.alert(commit.message, `${commit.author} · ${formatDate(commit.date)}`, [
      { text: "取消", style: "cancel" },
      {
        text: "Revert 此提交",
        style: "destructive",
        onPress: () => void run(
          () => new QwenPawClient(connection).mutateModule(
            "/workspace/git/revert",
            "POST",
            { commit_hash: commit.hash },
          ),
          "已创建 Revert 提交",
        ),
      },
    ]);
  }
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
