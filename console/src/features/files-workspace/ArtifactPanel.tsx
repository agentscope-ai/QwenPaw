import { Alert, Button, Empty, Popconfirm, Skeleton, message } from "antd";
import prettyBytes from "pretty-bytes";
import { useEffect, useState } from "react";
import { artifactsApi, type AgentArtifact } from "../../api/modules/artifacts";
import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import { personalLibraryApi } from "../../api/modules/personalLibrary";
import type { FileLocator } from "./fileLocator";
import styles from "./PersonalWorkspaceNavigator.module.less";

interface ArtifactPanelProps {
  refreshToken?: number;
  onLibraryChanged?: () => void;
  requestContext: AgentRequestContext;
  onOpen?: (locator: FileLocator) => void;
}

const sourceLabels: Record<string, string> = {
  send_file_to_user: "Agent 发送给我的文件",
  session_output: "会话产物目录",
  session_artifact_collector: "会话生成的文件（已自动归档）",
  confirmed_conversation_recovery: "从已确认的源会话恢复",
  confirmed_legacy_artifact_recovery: "从已确认的历史产物恢复",
};

export default function ArtifactPanel({onLibraryChanged, onOpen, requestContext, refreshToken = 0}: ArtifactPanelProps) {
  const [items, setItems] = useState<AgentArtifact[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  const [collecting, setCollecting] = useState(false);
  useEffect(() => {
    let active = true;
    setFailed(false);
    setItems(null);
    void artifactsApi.list(requestContext).then(result => { if (active) setItems(result); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [revision, refreshToken, requestContext.agentId, requestContext.governance]);
  const saveToLibrary = async (item: AgentArtifact) => {
    try {
      const document = await personalLibraryApi.copyArtifact({
        sourcePath: item.relative_path,
        destinationPath: `artifacts/${item.original_name}`,
      }, requestContext);
      message.success(`已保存到个人资料库：${document.relative_path}`);
      onLibraryChanged?.();
    } catch {
      message.error("保存到个人资料库失败，请检查是否存在同名文件");
    }
  };
  const collect = async () => {
    setCollecting(true);
    try {
      const result = await artifactsApi.collect(requestContext);
      if (result.failures.length > 0) {
        message.warning(`已登记 ${result.collected} 个文件，${result.failures.length} 个文件失败；请检查文件是否仍存在后重试`);
      } else {
        message.success(result.collected > 0 ? `已登记 ${result.collected} 个产物` : "未发现遗漏的产物");
      }
      setRevision((value) => value + 1);
    } catch {
      message.error("检查未登记文件失败，请确认源会话仍存在后重试");
    } finally {
      setCollecting(false);
    }
  };
  if (failed) return <Alert type="error" showIcon message="产物加载失败" description="无法确认产物列表，请重试。已有文件不会因此被删除。" action={<Button aria-label="重试" onClick={() => setRevision(value => value + 1)}>重试</Button>} />;
  if (items === null) return <Skeleton active paragraph={{ rows: 4 }} />;
  return <section className={styles.attachmentList} aria-label="产物">
    <header className={styles.sectionHeading}><div><strong>产物</strong><span>当前 Agent 在会话中生成并登记给你的文件</span></div><Button onClick={() => setRevision(value => value + 1)}>刷新列表</Button><Button loading={collecting} onClick={() => void collect()}>检查未登记文件</Button></header>
    {items.length === 0 ? <Empty description="暂无已登记产物" /> : null}
    {items.map((item) => <article key={item.id} className={styles.attachmentCard}>
      <div className={styles.attachmentBody}><strong>{item.original_name}</strong><span>{prettyBytes(item.size)} · {sourceLabels[item.source_tool] ?? "Agent 生成的文件"}{item.conversation_id ? ` · 来源会话 ${item.conversation_id}` : ""}</span></div>
      <Button size="small" onClick={() => void saveToLibrary(item)}>保存到个人资料库</Button>
      <Button size="small" disabled={!requestContext.agentId} onClick={() => requestContext.agentId && onOpen?.({category: "artifact", agentId: requestContext.agentId, stableId: item.id, relativePath: item.original_name, conversationId: item.conversation_id ?? undefined})}>查看</Button>
      <Button size="small" onClick={() => void artifactsApi.download(item.id, item.original_name, requestContext).catch(() => message.error("下载产物失败，文件可能已缺失；请检查未登记文件或重试"))}>下载</Button>
      <Popconfirm title="确定删除此产物？" onConfirm={() => void artifactsApi.remove(item.id, requestContext).then(() => setItems((current) => current?.filter((entry) => entry.id !== item.id) ?? [])).catch(() => message.error("删除产物失败，文件可能已被删除；请刷新后重试"))}>
        <Button size="small" danger>删除</Button>
      </Popconfirm>
    </article>)}
  </section>;
}
