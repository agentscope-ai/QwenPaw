import { useCallback, useEffect, useRef } from "react";
import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import { WorkbenchSurface } from "@/pages/R2VWorkbenchPage";
import type { TimelineElementDocument } from "@/contracts/creator";

/**
 * 制作台整页视图（片段编辑层设计 84:43404/84:38986/84:32995/84:44395）：
 * 覆盖工作区列（absolute inset-0），顶部保留 TopNav、左侧 AgentDock 不受影响；
 * WorkbenchSurface 自带 返回+元素名 页头与放弃/应用修改，脏草稿由其守卫。
 */
export default function WorkbenchModal({
  projectId,
  element,
  timelineId = null,
  onClose,
}: {
  projectId: string;
  element: TimelineElementDocument;
  timelineId?: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const dirtyRef = useRef(false);

  // Escape 关闭守护：制作台内有未应用修改时先确认（与页头返回一致）。
  const requestClose = useCallback(() => {
    if (!dirtyRef.current) {
      onClose();
      return;
    }
    Modal.confirm({
      title: t("workbench.unsavedChangesTitle"),
      content: t("workbench.closeDiscardDesc"),
      okText: t("workbench.discardAndClose"),
      okButtonProps: { danger: true },
      cancelText: t("workbench.continueEditing"),
      onOk: onClose,
    });
  }, [onClose, t]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA)$/.test(target.tagName)) return;
      requestClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [requestClose]);

  return (
    <div
      data-workbench-modal={element.element_id}
      className="panel-enter absolute inset-0 z-[60] flex min-h-0 flex-col bg-[var(--color-bg-layout)]"
    >
      <WorkbenchSurface
        projectId={projectId}
        elementId={element.element_id}
        timelineId={timelineId}
        onBack={onClose}
        onDirtyChange={(dirty) => {
          dirtyRef.current = dirty;
        }}
      />
    </div>
  );
}
