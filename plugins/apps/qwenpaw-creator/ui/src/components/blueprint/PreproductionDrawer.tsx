import { useEffect, useState } from "react";
import { Tabs, message } from "antd";
import { ArrowLeft, Globe, RefreshCw, X } from "lucide-react";
import type { DetailData, ResearchItem, VisualItem } from "./demoData";
import { GRADS, TONE_CHIP, TONE_TEXT } from "./demoData";

function KvLines({ kv }: { kv: [string, string][] }) {
  return (
    <div>
      {kv.map(([key, value]) => (
        <div
          key={key}
          className="flex justify-between gap-2.5 border-b border-dashed border-[var(--color-border)] py-1.5 text-xs last:border-b-0"
        >
          <span className="shrink-0 text-[var(--color-text-tertiary)]">
            {key}
          </span>
          <span className="text-right text-[var(--color-text-primary)]">
            {value}
          </span>
        </div>
      ))}
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
      {children}
    </span>
  );
}

export function DetailView({
  detail,
  onBack,
}: {
  detail: DetailData;
  onBack: () => void;
}) {
  const [messageApi, contextHolder] = message.useMessage();
  return (
    <div className="panel-enter flex h-full min-h-0 flex-col">
      {contextHolder}
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex w-fit items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        返回列表
      </button>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-2">
        {detail.type === "visual" && (
          <>
            <div
              className="flex min-h-[220px] items-end rounded-[10px] border border-[var(--color-border)] p-2.5 text-xs font-semibold text-white [text-shadow:0_1px_3px_rgba(0,0,0,.6)]"
              style={{ backgroundImage: GRADS[detail.grad] }}
            >
              {detail.title}
            </div>
            <div>
              <FieldLabel>版本</FieldLabel>
              <div className="flex flex-wrap gap-1.5">
                {detail.versions.map((version, index) => (
                  <button
                    key={version}
                    type="button"
                    className={`inline-flex h-[26px] items-center rounded-full border px-3 text-[11px] font-semibold transition-colors ${
                      index === detail.selected
                        ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                        : "border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-strong)]"
                    }`}
                  >
                    {version}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <FieldLabel>信息</FieldLabel>
              <KvLines kv={detail.kv} />
            </div>
            <div>
              <FieldLabel>
                设计 Prompt（可编辑，保存后重新生成新版本）
              </FieldLabel>
              <textarea
                data-creator-field="blueprint/visual-prompt"
                data-creator-field-label={`${detail.title} · Prompt`}
                defaultValue={detail.prompt}
                className="min-h-[96px] w-full resize-y rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-xs leading-relaxed text-[var(--color-text-primary)] outline-none transition-colors focus:border-[var(--color-accent)] focus:shadow-[0_0_0_2px_rgba(255,127,22,.1)]"
              />
            </div>
            <div className="mt-auto flex items-center gap-2 pt-1">
              <button
                type="button"
                className="btn-secondary shrink-0"
                onClick={() =>
                  messageApi.success("已按当前 prompt 排队重新生成")
                }
              >
                <RefreshCw className="h-3.5 w-3.5" />
                重新生成
              </button>
              <span className="text-[10px] leading-relaxed text-[var(--color-text-tertiary)]">
                设计确认在创作助手的待决策卡中完成，此处仅编辑
              </span>
            </div>
          </>
        )}
        {detail.type === "research" && (
          <>
            <div
              data-creator-field="blueprint/research-conclusion"
              data-creator-field-label={`${detail.title} · 结论`}
            >
              <FieldLabel>调研结论</FieldLabel>
              <p className="text-xs leading-relaxed text-[var(--color-text-primary)]">
                {detail.conclusion}
              </p>
            </div>
            <div>
              <FieldLabel>调研过程（browser use · 逐页可溯源）</FieldLabel>
              {detail.pages.map(([page, note]) => (
                <div
                  key={page}
                  className="flex items-baseline gap-2 rounded-md px-2 py-1.5 text-xs leading-relaxed hover:bg-[var(--color-bg-secondary)]"
                >
                  <Globe className="h-3 w-3 shrink-0 translate-y-0.5 text-[var(--color-primary,#3b82f6)]" />
                  <span className="text-[var(--color-text-secondary)]">
                    <b className="text-[var(--color-text-primary)]">{page}</b>
                    <br />
                    {note}
                  </span>
                </div>
              ))}
            </div>
            <div className="rounded-r-lg border-l-[3px] border-[var(--color-accent)] bg-[var(--color-accent-soft)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
              {detail.inject}
            </div>
            <div className="mt-auto flex items-center gap-2 pt-1">
              <button
                type="button"
                className="btn-secondary shrink-0"
                onClick={() => messageApi.success("已通知创作助手补充调研")}
              >
                补充调研
              </button>
              <span className="text-[10px] leading-relaxed text-[var(--color-text-tertiary)]">
                结论采纳 / 驳回在创作助手的待决策卡中完成
              </span>
            </div>
          </>
        )}
        {detail.type === "source" && (
          <>
            <div>
              <FieldLabel>理解概要</FieldLabel>
              <KvLines kv={detail.kv} />
            </div>
            <div
              data-creator-field="blueprint/source-segments"
              data-creator-field-label={`${detail.title} · 关键分段`}
            >
              <FieldLabel>关键分段（点击时间码 / 区间回看）</FieldLabel>
              {detail.segs.map(([timecode, text]) => (
                <div
                  key={timecode + text}
                  className="flex items-baseline gap-2 rounded-md px-2 py-1.5 text-xs leading-relaxed hover:bg-[var(--color-bg-secondary)]"
                >
                  <button
                    type="button"
                    onClick={() => messageApi.info(`（演示）回看 ${timecode}`)}
                    className="shrink-0 text-[11px] font-semibold tabular-nums text-[var(--color-primary,#3b82f6)] hover:underline"
                  >
                    {timecode}
                  </button>
                  <span className="text-[var(--color-text-secondary)]">
                    {text}
                  </span>
                </div>
              ))}
            </div>
            <div className="rounded-r-lg border-l-[3px] border-[var(--color-accent)] bg-[var(--color-accent-soft)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
              {detail.note}
            </div>
            <div className="mt-auto flex gap-2 pt-1">
              <button
                type="button"
                className="btn-secondary flex-1 justify-center"
                onClick={() => messageApi.success("已排队重新解析")}
              >
                重新解析
              </button>
              <button
                type="button"
                className="btn-primary flex-1 justify-center"
                onClick={() => {
                  messageApi.success("已在脚本中插入引用");
                  onBack();
                }}
              >
                在脚本中引用
              </button>
            </div>
          </>
        )}
        {detail.type === "interaction" && (
          <>
            <div>
              <FieldLabel>
                交互预览（真实可点击 · 渲染于上一片段末帧之上）
              </FieldLabel>
              <div
                className="relative flex aspect-[9/16] max-h-[300px] w-full flex-col items-center justify-end overflow-hidden rounded-[10px] border border-[var(--color-border)] pb-5"
                style={{ backgroundImage: GRADS[detail.lastFrame.grad] }}
              >
                <span className="absolute left-2 top-2 rounded bg-black/55 px-2 py-0.5 text-[9px] font-bold text-white">
                  {detail.lastFrame.label}
                </span>
                <span className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-full border-2 border-[var(--color-warning)] bg-black/40 text-[10px] font-bold text-white">
                  10s
                </span>
                <p className="mb-3 px-6 text-center text-xs font-semibold text-white [text-shadow:0_1px_3px_rgba(0,0,0,.7)]">
                  {detail.title.split(" · ").slice(1).join(" · ") ||
                    detail.title}
                </p>
                {detail.options.map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    onClick={() =>
                      messageApi.success(
                        `（可交互）命中选项：${option.label} → 跳转 ${option.target}`,
                      )
                    }
                    className="mb-2 w-[78%] rounded-lg border border-white/40 bg-black/35 px-3 py-2 text-xs font-bold text-white backdrop-blur transition-all hover:scale-[1.03] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent)]/70"
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <FieldLabel>选项（来自分支连线，修改连线即同步更新）</FieldLabel>
              {detail.options.map((option) => (
                <div
                  key={option.label}
                  className="flex items-center justify-between gap-2.5 border-b border-dashed border-[var(--color-border)] py-1.5 text-xs last:border-b-0"
                >
                  <span
                    contentEditable
                    suppressContentEditableWarning
                    className="rounded px-1 font-semibold text-[var(--color-text-primary)] outline-none focus:bg-[var(--color-accent-soft)]"
                  >
                    {option.label}
                  </span>
                  <span className="shrink-0 text-[var(--color-text-tertiary)]">
                    → {option.target}
                  </span>
                </div>
              ))}
              <p className="mt-1.5 text-[10px] text-[var(--color-text-tertiary)]">
                {detail.countdown}
              </p>
            </div>
            <div>
              <FieldLabel>信息</FieldLabel>
              <KvLines kv={detail.kv} />
            </div>
            <div>
              <FieldLabel>
                动效设计 Prompt（html_css motion · 可编辑）
              </FieldLabel>
              <textarea
                data-creator-field="blueprint/interaction-motion"
                data-creator-field-label={`${detail.title} · 动效 Prompt`}
                defaultValue={detail.prompt}
                className="min-h-[80px] w-full resize-y rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-xs leading-relaxed text-[var(--color-text-primary)] outline-none transition-colors focus:border-[var(--color-accent)] focus:shadow-[0_0_0_2px_rgba(255,127,22,.1)]"
              />
            </div>
            <div className="mt-auto flex items-center gap-2 pt-1">
              <button
                type="button"
                className="btn-secondary shrink-0"
                onClick={() =>
                  messageApi.success("已按当前设计重新生成交互动效")
                }
              >
                <RefreshCw className="h-3.5 w-3.5" />
                重新生成动效
              </button>
              <span className="text-[10px] leading-relaxed text-[var(--color-text-tertiary)]">
                交互确认在创作助手中完成；互动包待全部分支成片后组装
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export type PreproductionTab = "visual" | "research";

interface PreproductionDrawerProps {
  open: boolean;
  tab: PreproductionTab;
  visual: VisualItem[] | null;
  research: ResearchItem[];
  focusDetail: DetailData | null;
  onClose: () => void;
  onTabChange: (tab: PreproductionTab) => void;
}

export default function PreproductionDrawer({
  open,
  tab,
  visual,
  research,
  focusDetail,
  onClose,
  onTabChange,
}: PreproductionDrawerProps) {
  const [detail, setDetail] = useState<DetailData | null>(null);
  useEffect(() => {
    setDetail(focusDetail);
  }, [focusDetail, open]);

  if (!open) return null;

  return (
    <div
      className="absolute inset-0 z-30 flex justify-end bg-[rgba(20,16,12,.18)]"
      onClick={onClose}
    >
      <div
        className="panel-enter flex h-full w-[min(560px,92%)] flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-[-8px_0_28px_rgba(0,0,0,.08)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
          <span className="text-sm font-semibold text-[var(--color-text-primary)]">
            前置产物
          </span>
          <button
            type="button"
            onClick={onClose}
            className="icon-button !h-7 !w-7"
            title="关闭（选中引用保留在创作助手中）"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pb-5 pt-2">
          {detail ? (
            <DetailView detail={detail} onBack={() => setDetail(null)} />
          ) : (
            <Tabs
              activeKey={tab}
              onChange={(key) => onTabChange(key as PreproductionTab)}
              items={[
                ...(visual
                  ? [
                      {
                        key: "visual",
                        label: `视觉开发 (${visual.length})`,
                        children: (
                          <div className="grid grid-cols-2 gap-2.5 pt-2">
                            {visual.map((item) => (
                              <button
                                key={item.name}
                                type="button"
                                onClick={() => setDetail(item.detail)}
                                className={`overflow-hidden rounded-[10px] border bg-[var(--color-bg-card)] text-left transition-all hover:border-[var(--color-accent)] hover:shadow-[var(--shadow-sm)] ${
                                  item.pending
                                    ? "border-[rgba(247,144,9,.55)]"
                                    : "border-[var(--color-border)]"
                                }`}
                              >
                                <div
                                  className="relative flex h-[108px] items-end p-1.5 text-[11px] font-semibold text-white [text-shadow:0_1px_3px_rgba(0,0,0,.6)]"
                                  style={{ backgroundImage: GRADS[item.grad] }}
                                >
                                  {item.name.split(" · ")[0]}
                                  <span className="absolute right-1.5 top-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[9px] font-bold [text-shadow:none]">
                                    {item.tag}
                                  </span>
                                </div>
                                <div className="px-2.5 py-2">
                                  <b className="block truncate text-[11px] font-semibold text-[var(--color-text-primary)]">
                                    {item.name}
                                  </b>
                                  <span
                                    className={`text-[10px] ${
                                      TONE_TEXT[item.tone]
                                    }`}
                                  >
                                    {item.state}
                                  </span>
                                </div>
                              </button>
                            ))}
                          </div>
                        ),
                      },
                    ]
                  : []),
                {
                  key: "research",
                  label: `调研与素材 (${research.length})`,
                  children: (
                    <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
                      {research.map((item) => (
                        <button
                          key={item.title}
                          type="button"
                          onClick={() => setDetail(item.detail)}
                          className="flex w-full items-start gap-2.5 border-b border-[var(--color-border)] px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-[var(--color-bg-secondary)]"
                        >
                          <span
                            className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-lg text-[13px]"
                            style={{ background: item.iconBg }}
                          >
                            {item.icon}
                          </span>
                          <span className="min-w-0 flex-1">
                            <b className="block truncate text-xs font-semibold text-[var(--color-text-primary)]">
                              {item.title}
                            </b>
                            <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
                              {item.summary}
                            </p>
                          </span>
                          <span
                            className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                              TONE_CHIP[item.tone]
                            }`}
                          >
                            {item.tag}
                          </span>
                        </button>
                      ))}
                    </div>
                  ),
                },
              ]}
            />
          )}
        </div>
      </div>
    </div>
  );
}
