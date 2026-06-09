import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ToolCall } from '@agentscope-ai/chat';
import type { TaskNode, FileItem, StreamEvent } from './types';
import { getStatusConfig } from './constants';
import LoadingDots from './LoadingDots';
import TextBlock from './TextBlock';
import ThinkingBlock from './ThinkingBlock';
import FetchDataBlock from '../FetchDataBlock';
import { downloadArtifactFile } from './artifactFileActions';
import ArtifactFileList from './ArtifactFileList';
import ArtifactFilePreviewPanel from './ArtifactFilePreviewPanel';
import {
  collectDrawerFiles,
  type DrawerFileItem,
} from './fileUtils';
import styles from './TaskNodeDrawer.module.less';

interface TaskNodeDrawerProps {
  /** 当前选中的任务节点，为 null 时不渲染 */
  node: TaskNode | null;
  /** 所有节点的文件聚合（附带来源节点名称） */
  allFiles?: (FileItem & { _nodeName?: string })[];
  /** 是否正在流式传输 */
  isStreaming?: boolean;
  /** 统一的 SSE 事件流（按到达时序） */
  streamEvents?: StreamEvent[];
  /** 当前会话 ID */
  sessionId: string;
  /** 当前用户 ID */
  userId: string;
  /** 关闭抽屉的回调 */
  onClose: () => void;
}

/**
 * TaskNodeDrawer 组件
 * 右侧滑出的抽屉面板，用于展示任务节点的执行追踪和关联文件
 * 包含"实时跟随"和"文件"两个 Tab 页签
 */
export default function TaskNodeDrawer({ node, allFiles = [], isStreaming = false, streamEvents = [], sessionId, userId, onClose }: TaskNodeDrawerProps) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<'follow' | 'files'>('follow');
  const [viewingFile, setViewingFile] = useState<FileItem | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const isUserScrollingRef = useRef(false);
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /**
   * 监听 Escape 键：优先关闭文件预览，再关闭抽屉
   * 打开抽屉时禁止背景滚动
   */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (viewingFile) {
          setViewingFile(null);
        } else {
          onClose();
        }
      }
    };

    if (node) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [node, onClose, viewingFile]);

  /**
   * 监听用户滚动行为，用户主动向上滚动时暂停自动跟随
   */
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    const handleScroll = () => {
      const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      isUserScrollingRef.current = !isAtBottom;

      if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current);
      if (isAtBottom) {
        isUserScrollingRef.current = false;
      } else {
        // 用户向上滚动 3s 后自动恢复跟随
        scrollTimerRef.current = setTimeout(() => {
          isUserScrollingRef.current = false;
        }, 3000);
      }
    };

    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      el.removeEventListener('scroll', handleScroll);
      if (scrollTimerRef.current) clearTimeout(scrollTimerRef.current);
    };
  }, []);

  /**
   * streamEvents 更新时，如果正在流式且用户未主动滚动，自动滚到底部
   */
  const streamEventsLengthRef = useRef(streamEvents.length);
  useEffect(() => {
    if (!isStreaming) return;
    if (isUserScrollingRef.current) return;
    if (activeTab !== 'follow') return;
    const el = contentRef.current;
    if (!el) return;

    if (streamEvents.length > streamEventsLengthRef.current) {
      streamEventsLengthRef.current = streamEvents.length;
      requestAnimationFrame(() => {
        if (!isUserScrollingRef.current && contentRef.current) {
          contentRef.current.scrollTop = contentRef.current.scrollHeight;
        }
      });
    }
  }, [streamEvents.length, isStreaming, activeTab]);

  const streamContentSize = streamEvents.reduce((size, event) => {
    if (event.type === 'text') return size + event.text.length;
    if (event.type === 'thinking') return size + event.thinking.length;
    if (event.type === 'tool_call') {
      return size + (event.arguments?.length ?? 0) + (event.output?.length ?? 0);
    }
    return size;
  }, 0);

  useEffect(() => {
    if (!isStreaming) return;
    if (isUserScrollingRef.current) return;
    if (activeTab !== 'follow') return;
    if (streamEvents.length === 0) return;
    requestAnimationFrame(() => {
      if (!isUserScrollingRef.current && contentRef.current) {
        contentRef.current.scrollTop = contentRef.current.scrollHeight;
      }
    });
  }, [streamEvents.length, streamContentSize, isStreaming, activeTab]);

  /**
   * 切换节点时重置滚动位置和用户滚动状态
   */
  const prevNodeIdRef = useRef(node?.node_id);
  useEffect(() => {
    if (node?.node_id !== prevNodeIdRef.current) {
      prevNodeIdRef.current = node?.node_id;
      isUserScrollingRef.current = false;
      streamEventsLengthRef.current = 0;
      if (contentRef.current) {
        contentRef.current.scrollTop = 0;
      }
      // 打开时自动切换到 follow tab
      setActiveTab('follow');
      setViewingFile(null);
    }
  }, [node?.node_id]);

  const handleDownloadFile = async (file: FileItem) => {
    try {
      await downloadArtifactFile(file, sessionId, userId);
    } catch (e) {
      console.error('Download failed:', e);
    }
  };

  if (!node) return null;

  const files: DrawerFileItem[] = collectDrawerFiles(
    node.output?.files,
    allFiles,
    node.name || node.node_id,
  );
  const statusConfig = getStatusConfig(node.state);

  return (
    <>
      <div className={styles.overlay} onClick={onClose} />
      <div className={styles.drawer}>
        <div className={styles.drawerHeader}>
          <div className={styles.headerLeft}>
            <span className={styles.nodeName}>{node.name || node.node_id}</span>
            <span className={`${styles.nodeStatus} ${styles[statusConfig.className] || ''}`}>
              {statusConfig.icon} {t(statusConfig.label)}
            </span>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.closeBtn} onClick={onClose}>✕</button>
          </div>
        </div>

        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${activeTab === 'follow' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('follow')}
          >
            {t('taskGraph.tabFollow')}
          </button>
          <button
            className={`${styles.tab} ${activeTab === 'files' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('files')}
          >
            {t('taskGraph.tabFiles')}{files.length > 0 ? ` (${files.length})` : ''}
          </button>
        </div>

        <div className={styles.drawerContent} ref={contentRef}>
          {activeTab === 'follow' && (
            <>
              {node.type && (
                <div className={styles.agentTitle}>
                  <span className={styles.agentBadge}>{node.type}</span>
                </div>
              )}

              {streamEvents.map((event, idx) => {
                if (event.type === 'text') {
                  return <TextBlock key={`text-${idx}`} content={event.text} />;
                } else if (event.type === 'tool_call') {
                  // fetch_data 工具调用使用通用 FetchDataBlock 组件（主 Chat 和抽屉共用）
                  if (event.name === 'fetch_data') {
                    return (
                      <FetchDataBlock
                        key={event.call_id || `tool-${idx}`}
                        argumentsStr={event.arguments}
                        output={event.output}
                        loading={!event.output}
                        fallbackTitle={event.name}
                      />
                    );
                  }

                  // 其他工具调用使用默认 ToolCall 组件
                  let inputContent = event.arguments || '{}';
                  if (typeof inputContent === 'object') {
                    inputContent = JSON.stringify(inputContent, null, 2);
                  }
                  let outputContent = event.output || '';
                  if (outputContent && typeof outputContent === 'string') {
                    try {
                      outputContent = JSON.stringify(JSON.parse(outputContent), null, 2);
                    } catch {
                      // 非 JSON 格式，保持原样
                    }
                  }
                  return (
                    <ToolCall
                      key={event.call_id || `tool-${idx}`}
                      title={event.name}
                      input={inputContent}
                      output={outputContent}
                      defaultOpen={false}
                    />
                  );
                } else if (event.type === 'thinking') {
                  return <ThinkingBlock key={`thinking-${idx}`} content={event.thinking} />;
                }
                return null;
              })}

              {streamEvents.length === 0 && !isStreaming && (
                <div className={styles.emptyState}>{t('taskGraph.noTrace')}</div>
              )}

              {isStreaming && <LoadingDots />}
            </>
          )}

          {activeTab === 'files' && (
            <div className={styles.filesTab}>
              {viewingFile ? (
                <ArtifactFilePreviewPanel
                  file={viewingFile}
                  sessionId={sessionId}
                  userId={userId}
                  onBack={() => setViewingFile(null)}
                />
              ) : (
                <ArtifactFileList
                  files={files}
                  onPreview={setViewingFile}
                  onDownload={handleDownloadFile}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
