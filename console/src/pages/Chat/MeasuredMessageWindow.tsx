import {
  Component,
  cloneElement,
  createElement,
  type ReactElement,
  type ContextType,
  type ReactNode,
  type HTMLAttributes,
} from "react";
import { MessageWindowStateContext } from "./messageWindowState";

export const MESSAGE_WINDOW_LIMIT = 32;
export const RESPONSE_WINDOW_LIMIT = 128;
const SCROLLER =
  '[data-history-message-window="true"], [class*="chat-anywhere-message-list-bubble-scroll"]';
const windows = new WeakMap<HTMLElement, MeasuredMessageWindow>();

export function revealCachedMessage(
  scroll: HTMLElement,
  id: string,
  ready: () => void,
): boolean {
  for (const root of scroll.querySelectorAll<HTMLElement>(
    "[data-measured-message-window]",
  )) {
    if (windows.get(root)?.reveal(id, ready)) return true;
  }
  return false;
}

interface Props {
  tableColumns?: number;
  cacheKey?: string;
  ids: string[];
  children: (index: number) => ReactNode;
  gap?: number;
  estimate?: number;
  initialEnd?: boolean;
  maxItems?: number;
}
interface Anchor {
  id: string;
  offset: number;
}

/** The data can grow; only a fixed number of message bodies is mounted. */
export class MeasuredMessageWindow extends Component<
  Props,
  { first?: string; count?: number }
> {
  static contextType = MessageWindowStateContext;
  declare context: ContextType<typeof MessageWindowStateContext>;
  state: { first?: string; count?: number } = {};
  private root: HTMLElement | null = null;
  private scroll: HTMLElement | null = null;
  private observer?: ResizeObserver;
  private heights = new Map<string, number>();
  private offsets: number[] = [];
  private start = 0;
  private end = 0;
  private frame = 0;
  private mounted = false;

  private rows() {
    return Array.from(this.root?.children ?? []).filter(
      (node): node is HTMLElement =>
        node instanceof HTMLElement && node.hasAttribute("data-window-row"),
    );
  }

  private anchor(): Anchor | null {
    if (!this.scroll) return null;
    const viewport = this.scroll.getBoundingClientRect();
    const top = viewport.top;
    const row = this.rows().find((node) => {
      const bounds = node.getBoundingClientRect();
      return bounds.bottom > top && bounds.top < viewport.bottom;
    });
    return row
      ? {
          id: row.dataset.windowRow!,
          offset: row.getBoundingClientRect().top - top,
        }
      : null;
  }

  private restore(anchor: Anchor | null) {
    if (!anchor || !this.scroll) return;
    const row = this.rows().find(
      (node) => node.dataset.windowRow === anchor.id,
    );
    if (!row) return;
    const delta =
      row.getBoundingClientRect().top -
      this.scroll.getBoundingClientRect().top -
      anchor.offset;
    if (Math.abs(delta) > 0.5) this.scroll.scrollTop += delta;
  }

  private measure = () => {
    if (!this.mounted) return;
    const anchor = this.anchor();
    let changed = false;
    for (const row of this.rows()) {
      const height =
        row.getBoundingClientRect().height -
        (Number.parseFloat(row.style.paddingBottom) || 0);
      const previousHeight = this.heights.get(row.dataset.windowRow!);
      if (
        height > 0 &&
        (previousHeight === undefined ||
          Math.abs(previousHeight - height) > 0.5)
      ) {
        this.heights.set(row.dataset.windowRow!, height);
        changed = true;
      }
    }
    if (changed) {
      this.forceUpdate(() => {
        this.restore(anchor);
        this.onScroll();
      });
    }
  };

  private updateRange = () => {
    if (
      !this.root ||
      !this.scroll ||
      this.props.ids.length <= MESSAGE_WINDOW_LIMIT
    )
      return;
    const viewport = this.scroll.getBoundingClientRect();
    const bounds = this.root.getBoundingClientRect();
    if (
      this.scroll.clientHeight > 0 &&
      (bounds.bottom <= viewport.top || bounds.top >= viewport.bottom)
    )
      return;
    const relativeTop = viewport.top - bounds.top;
    let low = 0;
    let high = this.props.ids.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (this.offsets[middle + 1] <= relativeTop) low = middle + 1;
      else high = middle;
    }
    const start = Math.min(
      Math.max(0, low - 8),
      Math.max(0, this.props.ids.length - MESSAGE_WINDOW_LIMIT),
    );
    const relativeBottom = relativeTop + this.scroll.clientHeight;
    let visibleEnd = low;
    while (
      visibleEnd < this.props.ids.length &&
      this.offsets[visibleEnd] < relativeBottom
    ) {
      visibleEnd += 1;
    }
    const count = Math.min(
      this.props.maxItems ?? MESSAGE_WINDOW_LIMIT,
      Math.max(MESSAGE_WINDOW_LIMIT, visibleEnd + 8 - start),
    );
    if (
      start !== this.start ||
      count !== (this.state.count ?? MESSAGE_WINDOW_LIMIT)
    )
      this.setState({ first: this.props.ids[start], count });
  };

  private onScroll = () => {
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(this.updateRange);
  };

  componentDidMount() {
    this.mounted = true;
    if (this.root) windows.set(this.root, this);
    this.scroll = this.root?.closest<HTMLElement>(SCROLLER) ?? null;
    this.scroll?.addEventListener("scroll", this.onScroll, { passive: true });
    if (typeof ResizeObserver !== "undefined") {
      this.observer = new ResizeObserver(this.measure);
      this.observe();
    }
    this.measure();
    this.onScroll();
  }

  private observe() {
    this.observer?.disconnect();
    this.rows().forEach((row) => this.observer?.observe(row));
  }

  getSnapshotBeforeUpdate(): Anchor | null {
    return this.anchor();
  }

  componentDidUpdate(_previous: Props, _state: unknown, anchor: Anchor | null) {
    this.restore(anchor);
    this.observe();
    this.measure();
    if (_previous.ids !== this.props.ids) this.onScroll();
    this.root?.dispatchEvent(
      new Event("chat-message-window-rendered", { bubbles: true }),
    );
  }

  componentWillUnmount() {
    this.mounted = false;
    cancelAnimationFrame(this.frame);
    this.scroll?.removeEventListener("scroll", this.onScroll);
    this.observer?.disconnect();
    if (this.root) windows.delete(this.root);
  }

  reveal(id: string, ready: () => void): boolean {
    const index = this.props.ids.indexOf(id);
    if (index < 0) return false;
    const start = Math.max(
      0,
      Math.min(index - 4, this.props.ids.length - MESSAGE_WINDOW_LIMIT),
    );
    this.setState({ first: this.props.ids[start] }, ready);
    return true;
  }

  render() {
    if (this.props.cacheKey && this.context) {
      const saved = this.context.heights.get(this.props.cacheKey);
      if (saved) this.heights = saved;
      else this.context.heights.set(this.props.cacheKey, this.heights);
    }
    const { ids, gap = 0, estimate = 240 } = this.props;
    const previousFirst = this.state.first;
    const index = previousFirst ? ids.indexOf(previousFirst) : -1;
    this.start = Math.max(
      0,
      Math.min(
        ids.length - MESSAGE_WINDOW_LIMIT,
        index >= 0
          ? index
          : this.props.initialEnd
          ? ids.length - MESSAGE_WINDOW_LIMIT
          : 0,
      ),
    );
    this.end = Math.min(
      ids.length,
      this.start + (this.state.count ?? MESSAGE_WINDOW_LIMIT),
    );
    this.offsets = [0];
    ids.forEach((id, index) =>
      this.offsets.push(
        this.offsets[this.offsets.length - 1] +
          (this.heights.get(id) ?? estimate) +
          (index + 1 < ids.length ? gap : 0),
      ),
    );
    const spacer = (height: number, key: string) =>
      this.props.tableColumns ? (
        <tr key={key} aria-hidden="true">
          <td
            colSpan={this.props.tableColumns}
            style={{ height, padding: 0, border: 0 }}
          />
        </tr>
      ) : (
        <div key={key} aria-hidden="true" style={{ height }} />
      );
    return createElement(
      this.props.tableColumns ? "tbody" : "div",
      {
        ref: (node: HTMLElement | null) => {
          this.root = node;
        },
        "data-measured-message-window": "true",
      },
      [
        spacer(this.offsets[this.start], "before"),
        ...ids.slice(this.start, this.end).map((id, offset) => {
          const index = this.start + offset;
          const child = this.props.children(index);
          if (this.props.tableColumns)
            return cloneElement(
              child as ReactElement<
                HTMLAttributes<HTMLTableRowElement> & {
                  "data-window-row"?: string;
                }
              >,
              { key: id, "data-window-row": id },
            );
          return (
            <div
              key={id}
              data-window-row={id}
              style={{
                display: "flow-root",
                paddingBottom: index + 1 < ids.length ? gap : 0,
              }}
            >
              {child}
            </div>
          );
        }),
        spacer(
          this.end < ids.length
            ? this.offsets[ids.length] - this.offsets[this.end]
            : 0,
          "after",
        ),
      ],
    );
  }
}
