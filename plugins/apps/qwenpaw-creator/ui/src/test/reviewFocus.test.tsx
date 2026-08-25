import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  flashCreatorReviewField,
  useReviewFieldFocus,
} from "@/routing/reviewFocus";
import { useNavigationStore } from "@/store/navigationStore";

const PATH = "/project/p1/plan";
const FIELD = "element:element-1/label";
const FIELD_B = "element:element-1/creation/video_prompt";

const q = (container: HTMLElement, selector = "[data-creator-field]") =>
  container.querySelector<HTMLElement>(selector)!;

const focusField = (field: string, reviewPulse: string) =>
  act(() => {
    useNavigationStore.getState().setReviewFocus({
      path: PATH,
      ref: "element:element-1",
      query: { review: "1", field, reviewPulse },
    });
  });

type HarnessProps = { showTarget?: boolean; pulse: string };

function Harness({ showTarget = true, pulse }: HarnessProps) {
  useReviewFieldFocus({ path: PATH, field: FIELD, enabled: true, pulse });
  return showTarget ? <div data-creator-field={FIELD}>原文</div> : null;
}

function MultiFieldHarness({ pulse }: { pulse: string }) {
  useReviewFieldFocus({ path: PATH, field: FIELD, enabled: true, pulse });
  return (
    <>
      <div data-creator-field={FIELD}>原文 A</div>
      <div data-creator-field={FIELD_B}>原文 B</div>
    </>
  );
}

function DockCollisionHarness({ pulse }: { pulse: string }) {
  useReviewFieldFocus({ path: PATH, field: FIELD, enabled: true, pulse });
  return (
    <>
      <aside data-agent-dock>
        <div data-creator-field={FIELD}>AgentDock diff</div>
      </aside>
      <main data-creator-workspace-root>
        <div data-creator-field={FIELD}>工作区正文</div>
      </main>
    </>
  );
}

describe("useReviewFieldFocus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useNavigationStore.setState({ reviewFocus: null });
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => vi.useRealTimers());

  it("URL 审阅定位会滚动并闪烁字段", () => {
    const { container } = render(<Harness pulse="pulse-url" />);
    const target = q(container);
    expect(target).toHaveClass("review-flash");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(2400));
    expect(target).not.toHaveClass("review-flash");
  });

  it("AgentDock 关闭后的同页兜底会立即重放字段闪烁", () => {
    const { container } = render(<div data-creator-field={FIELD}>原文</div>);
    const target = q(container);

    expect(flashCreatorReviewField(FIELD, container)).toBe(target);
    expect(target).toHaveClass("review-flash");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it("同名字段同时存在时只定位工作区，不会闪烁 AgentDock", () => {
    const { container } = render(<DockCollisionHarness pulse="pulse-dock" />);
    const dockTarget = q(container, "[data-agent-dock] [data-creator-field]");
    const workspaceTarget = q(
      container,
      "[data-creator-workspace-root] [data-creator-field]",
    );

    expect(workspaceTarget).toHaveClass("review-flash");
    expect(dockTarget).not.toHaveClass("review-flash");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it("同一字段的重复 reviewFocus 请求（新 pulse）会重放定位", () => {
    render(<Harness pulse="pulse-replay" />);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);

    focusField(FIELD, "pulse-replay-2");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(2);
  });

  it("已消费的 pulse 不会在重挂载/重渲染时重放定位动画", () => {
    const { unmount } = render(<Harness pulse="pulse-consumed" />);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
    unmount();

    render(<Harness pulse="pulse-consumed" />);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it("详情节点延迟挂载时会重试，不依赖固定 360ms", () => {
    const { container, rerender } = render(
      <Harness showTarget={false} pulse="pulse-retry" />,
    );
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(400));
    rerender(<Harness showTarget pulse="pulse-retry" />);
    act(() => vi.advanceTimersByTime(50));

    expect(q(container)).toHaveClass("review-flash");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it("切换查看字段会清理上一个目标的闪烁类", () => {
    const { container } = render(<MultiFieldHarness pulse="pulse-switch" />);
    const first = q(container, `[data-creator-field="${FIELD}"]`);
    const second = q(container, `[data-creator-field="${FIELD_B}"]`);
    expect(first).toHaveClass("review-flash");

    focusField(FIELD_B, "pulse-switch-2");

    expect(first).not.toHaveClass("review-flash");
    expect(second).toHaveClass("review-flash");
  });
});
