import { useEffect, useRef } from "react";
import { MessageSquarePlus, MousePointer2, Play } from "lucide-react";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";

/**
 * Mini mock UIs inside tour popovers: purely presentational elements that
 * imitate what each area looks like "with content", so users of an empty
 * project (the Agent is still planning a freshly created one) can still tell
 * where to click. All static demos — no real project data is read.
 */

function MockCaption({ children }: { children: string }) {
  return (
    <p className="mb-1 text-[10px] font-semibold text-[var(--color-text-tertiary)]">
      {children}
    </p>
  );
}

function MockFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-secondary)]/60 p-2">
      {children}
    </div>
  );
}

function ClickCursor({ label }: { label: string }) {
  return (
    <span className="pointer-events-none absolute -bottom-2.5 -right-1 z-[1] flex items-center gap-0.5 whitespace-nowrap">
      <MousePointer2 className="h-3 w-3 fill-[var(--color-text-primary)] text-[var(--color-text-primary)]" />
      <span className="rounded bg-[var(--color-text-primary)] px-1 py-px text-[9px] font-semibold text-white">
        {label}
      </span>
    </span>
  );
}

export function MockTimeline() {
  return (
    <MockFrame>
      <MockCaption>示例：规划完成后的时间轴</MockCaption>
      <div className="flex gap-1 text-[9px] text-[var(--color-text-tertiary)]">
        {["0s", "2s", "4s", "6s"].map((tick) => (
          <span key={tick} className="w-14">
            {tick}
          </span>
        ))}
      </div>
      <div className="mt-0.5 flex gap-1">
        <span className="relative flex h-6 w-24 items-center justify-center rounded border border-[var(--color-accent)]/60 bg-[var(--color-accent-soft)] text-[9px] font-semibold text-[var(--color-accent)]">
          画面 · 镜头一
          <ClickCursor label="点击查看详情" />
        </span>
        <span className="flex h-6 w-20 items-center justify-center rounded border border-emerald-300 bg-emerald-50 text-[9px] font-semibold text-emerald-600">
          画面 · 镜头二
        </span>
        <span className="flex h-6 w-12 items-center justify-center rounded border border-violet-300 bg-violet-50 text-[9px] font-semibold text-violet-600">
          转场
        </span>
      </div>
      <div className="mt-1 flex gap-1">
        <span className="flex h-4 w-32 items-center justify-center rounded border border-sky-300 bg-sky-50 text-[9px] text-sky-600">
          字幕动效
        </span>
        <span className="flex h-4 w-24 items-center justify-center rounded border border-amber-300 bg-amber-50 text-[9px] text-amber-600">
          声音 · 配乐
        </span>
      </div>
    </MockFrame>
  );
}

export function MockElementDetail() {
  return (
    <MockFrame>
      <MockCaption>示例：选中「镜头一」后的详情面板</MockCaption>
      <div className="rounded-md border border-[var(--color-border)] bg-white p-2">
        <div className="flex items-center gap-1.5">
          <span className="rounded-full bg-[var(--color-accent-soft)] px-1.5 py-px text-[9px] font-semibold text-[var(--color-accent)]">
            画面
          </span>
          <span className="text-[11px] font-semibold text-[var(--color-text-primary)]">
            镜头一
          </span>
        </div>
        <div className="mt-1.5 space-y-1 text-[10px]">
          <div className="flex gap-1.5">
            <span className="shrink-0 text-[var(--color-text-tertiary)]">
              画面描述
            </span>
            <span className="flex-1 truncate rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-1.5 text-[var(--color-text-secondary)]">
              晨雾山谷中，小狐狸跃上岩石…
            </span>
          </div>
          <div className="flex gap-1.5">
            <span className="shrink-0 text-[var(--color-text-tertiary)]">
              时长
            </span>
            <span className="rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-1.5 text-[var(--color-text-secondary)]">
              4.0s
            </span>
          </div>
        </div>
        <div className="mt-1.5 flex justify-end">
          <span className="relative rounded bg-[var(--color-accent)] px-2 py-0.5 text-[9px] font-semibold text-white">
            应用修改
            <ClickCursor label="编辑后点这里" />
          </span>
        </div>
      </div>
    </MockFrame>
  );
}

export function MockSelectionDemo() {
  const chip = (
    <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white px-1.5 py-0.5 text-[9px] font-semibold text-[var(--color-text-primary)] shadow-sm">
      <MessageSquarePlus className="h-3 w-3" />
      添加到对话
    </span>
  );
  return (
    <MockFrame>
      <MockCaption>示例：两种选中方式</MockCaption>
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <p className="text-[10px] leading-4 text-[var(--color-text-secondary)]">
            晨雾山谷中，
            <span className="rounded-sm bg-[var(--color-accent-soft)] px-0.5 text-[var(--color-accent)]">
              小狐狸跃上岩石
            </span>
            回望镜头…
          </p>
          {chip}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative h-4 w-40 overflow-hidden rounded border border-[var(--color-border)] bg-white">
            <span className="absolute inset-y-0 left-[30%] w-[40%] border-x border-[var(--color-accent)] bg-[var(--color-accent-soft)]" />
          </div>
          {chip}
        </div>
      </div>
    </MockFrame>
  );
}

export function MockAgentChat() {
  return (
    <MockFrame>
      <MockCaption>示例：一次修改对话</MockCaption>
      <div className="space-y-1">
        <p className="ml-auto w-fit max-w-[85%] rounded-lg bg-[var(--color-accent)] px-2 py-1 text-[10px] text-white">
          把 @镜头一 改成夜景氛围
        </p>
        <p className="w-fit max-w-[85%] rounded-lg bg-white px-2 py-1 text-[10px] text-[var(--color-text-secondary)]">
          好的，我会更新画面描述并重新生成分镜图。
        </p>
        <span className="inline-flex items-center gap-1 rounded border border-[var(--color-border)] bg-white px-1.5 py-0.5 text-[9px] text-[var(--color-text-tertiary)]">
          ⚙ 图像生成 · 镜头一 · 进行中
        </span>
      </div>
    </MockFrame>
  );
}

export function MockAssetCards() {
  const cards = [
    { label: "角色", name: "主角小狐", tone: "bg-orange-100 text-orange-500" },
    {
      label: "场景",
      name: "晨雾山谷",
      tone: "bg-emerald-100 text-emerald-500",
    },
    { label: "产物", name: "镜头一分镜图", tone: "bg-sky-100 text-sky-500" },
  ];
  return (
    <MockFrame>
      <MockCaption>示例：短剧项目的资产卡片</MockCaption>
      <div className="flex gap-1.5">
        {cards.map((card) => (
          <div
            key={card.name}
            className="w-20 overflow-hidden rounded-md border border-[var(--color-border)] bg-white"
          >
            <div
              className={`flex h-10 items-center justify-center text-[9px] font-bold ${card.tone}`}
            >
              {card.label}
            </div>
            <p className="truncate px-1 py-0.5 text-[9px] text-[var(--color-text-secondary)]">
              {card.name}
            </p>
          </div>
        ))}
      </div>
    </MockFrame>
  );
}

const DEMO_FIELD = "project:onboarding-demo";

/**
 * Live selection demo: programmatically selects a sample sentence inside the
 * popover so the real "添加到对话" (add to conversation) toolbar appears;
 * clicking it really puts the content into the AgentDock input (and if the
 * AgentDock is collapsed, it genuinely gets opened).
 */
export function LiveSelectionDemo() {
  const demoRef = useRef<HTMLSpanElement>(null);

  const runDemo = () => {
    const node = demoRef.current;
    const selection = window.getSelection();
    if (!node || !selection) return;
    // SelectionToolbar ignores selection changes while the AgentDock input holds
    // focus, so blur it first.
    const active = document.activeElement as HTMLElement | null;
    if (active && active.closest?.("[data-agent-dock]")) active.blur();
    const range = document.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
  };

  useEffect(() => {
    const timer = window.setTimeout(runDemo, 600);
    return () => {
      window.clearTimeout(timer);
      window.getSelection()?.removeAllRanges();
      const interaction = useCreatorInteractionStore.getState();
      if (interaction.selection?.field === DEMO_FIELD) {
        interaction.setSelection(null);
      }
    };
  }, []);

  return (
    <MockFrame>
      <MockCaption>试一试（真实操作）</MockCaption>
      <p
        data-creator-field={DEMO_FIELD}
        data-creator-field-label="引导示例文本"
        className="select-text text-[11px] leading-5 text-[var(--color-text-secondary)]"
      >
        晨雾山谷中，
        <span ref={demoRef}>小狐狸跃上岩石回望镜头</span>
        ，画面定格。
      </p>
      <div className="mt-1.5 flex items-center gap-2">
        <button
          type="button"
          onClick={runDemo}
          className="inline-flex cursor-pointer items-center gap-1 rounded-md bg-[var(--color-accent)] px-2 py-1 text-[10px] font-semibold text-white transition hover:opacity-90"
        >
          <Play className="h-3 w-3" />
          模拟选中这段文字
        </button>
        <span className="text-[10px] text-[var(--color-text-tertiary)]">
          选中后点浮出的「添加到对话」，内容会真正进入创作助手输入框
        </span>
      </div>
    </MockFrame>
  );
}

/**
 * Live collapse/expand demo: the button drives the real AgentDock toggle;
 * after collapsing, the real edge handle appears at the right screen edge and
 * clicking it genuinely expands the dock again.
 */
export function LiveDockToggleDemo() {
  const open = useAgentDockUiStore((state) => state.open);
  const setOpen = useAgentDockUiStore((state) => state.setOpen);
  return (
    <MockFrame>
      <MockCaption>试一试（真实操作）</MockCaption>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="inline-flex cursor-pointer items-center gap-1 rounded-md bg-[var(--color-accent)] px-2 py-1 text-[10px] font-semibold text-white transition hover:opacity-90"
        >
          <Play className="h-3 w-3" />
          {open ? "收起面板" : "展开面板"}
        </button>
        <span className="text-[10px] leading-4 text-[var(--color-text-tertiary)]">
          {open
            ? "面板当前已展开；收起后右缘会出现贴边把手"
            : "已收起：点击屏幕右缘的把手，或再点一次按钮展开"}
        </span>
      </div>
    </MockFrame>
  );
}
