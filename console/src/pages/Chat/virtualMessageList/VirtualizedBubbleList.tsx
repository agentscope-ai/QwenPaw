import React, {
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AT_NEWEST_PX,
  DEFAULT_ESTIMATED_ROW_HEIGHT,
  DEFAULT_OVERSCAN_PX,
  DEFAULT_ROW_GAP,
  NEAR_OLDEST_PX,
  accumulateOffsets,
  computeSpacers,
  getVisibleIndexRange,
  isAtNewestEdge,
  isNearOldestEdge,
  itemKey,
  reverseViewWindow,
  scrollTopForIndex,
} from "./range";
import styles from "./index.module.less";

export interface VirtualizedItem {
  id?: string;
  key?: string | number;
}

export interface VirtualizedBubbleListRef {
  scrollToBottom: () => void;
  scrollToItem: (id: string) => void;
}

export interface VirtualizedBubbleListProps<T extends VirtualizedItem> {
  items: T[];
  order?: "asc" | "desc";
  prefixCls?: string;
  className?: string;
  classNames?: {
    wrapper?: string;
    list?: string;
  };
  estimatedRowHeight?: number;
  gap?: number;
  overscanPx?: number;
  onStartReached?: () => void;
  renderItem: (item: T, index: number, isLast: boolean) => React.ReactNode;
  renderScrollToBottom?: (
    visible: boolean,
    onClick: () => void,
  ) => React.ReactNode;
}

interface MeasuredRowProps {
  id: string;
  onHeight: (id: string, height: number) => void;
  gapBefore?: number;
  children: React.ReactNode;
}

const MeasuredRow: React.FC<MeasuredRowProps> = ({
  id,
  onHeight,
  gapBefore = 0,
  children,
}) => {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const report = () => {
      const height = element.getBoundingClientRect().height;
      if (height > 0) onHeight(id, height);
    };
    report();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(report);
    observer.observe(element);
    return () => observer.disconnect();
  }, [id, onHeight]);

  return (
    <div
      ref={ref}
      className={styles.row}
      data-testid="virtual-message-row"
      data-message-id={id}
      style={gapBefore > 0 ? { marginTop: gapBefore } : undefined}
    >
      {children}
    </div>
  );
};

function VirtualizedBubbleListInner<T extends VirtualizedItem>(
  props: VirtualizedBubbleListProps<T>,
  ref: React.ForwardedRef<VirtualizedBubbleListRef>,
) {
  const {
    items,
    order = "desc",
    prefixCls = "qwenpaw-bubble-list",
    estimatedRowHeight = DEFAULT_ESTIMATED_ROW_HEIGHT,
    gap = DEFAULT_ROW_GAP,
    overscanPx = DEFAULT_OVERSCAN_PX,
    onStartReached,
    renderItem,
    renderScrollToBottom,
  } = props;
  const isDesc = order === "desc";

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const heightsRef = useRef<Map<string, number>>(new Map());
  const atNewestRef = useRef(true);
  const startReachedLockRef = useRef(false);
  const [heightVersion, setHeightVersion] = useState(0);
  const [scrollVersion, setScrollVersion] = useState(0);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);

  const keys = useMemo(
    () => items.map((item, index) => itemKey(item, index)),
    [items],
  );
  const newestKey = keys[0] ?? null;
  const oldestKey = keys.length > 0 ? keys[keys.length - 1] : null;
  const prevNewestKeyRef = useRef<string | null>(newestKey);

  const { offsets, sizes, total } = useMemo(
    () => accumulateOffsets(keys, heightsRef.current, estimatedRowHeight, gap),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- heightVersion tracks measured sizes in a ref
    [keys, estimatedRowHeight, gap, heightVersion],
  );

  const handleHeight = useCallback((id: string, height: number) => {
    const previous = heightsRef.current.get(id);
    if (previous === height) return;
    heightsRef.current.set(id, height);
    setHeightVersion((value) => value + 1);
  }, []);

  const scrollToBottom = useCallback(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    scroller.scrollTop = 0;
    atNewestRef.current = true;
    setShowScrollToBottom(false);
  }, []);

  const scrollToItem = useCallback(
    (id: string) => {
      const scroller = scrollRef.current;
      const index = keys.indexOf(id);
      if (!scroller || index < 0) return;
      scroller.scrollTop = isDesc
        ? scrollTopForIndex(
            index,
            offsets,
            sizes,
            scroller.clientHeight,
            "oldest",
          )
        : offsets[index];
      setScrollVersion((value) => value + 1);
    },
    [isDesc, keys, offsets, sizes],
  );

  useImperativeHandle(
    ref,
    () => ({
      scrollToBottom,
      scrollToItem,
    }),
    [scrollToBottom, scrollToItem],
  );

  useLayoutEffect(() => {
    if (!isDesc) return;
    if (newestKey !== prevNewestKeyRef.current) {
      if (atNewestRef.current) scrollToBottom();
      prevNewestKeyRef.current = newestKey;
    }
  }, [isDesc, newestKey, scrollToBottom]);

  useEffect(() => {
    startReachedLockRef.current = false;
  }, [oldestKey]);

  const readScroller = () => {
    const scroller = scrollRef.current;
    return {
      scrollTop: scroller?.scrollTop ?? 0,
      clientHeight: scroller?.clientHeight ?? 0,
      scrollHeight: scroller?.scrollHeight ?? 0,
    };
  };

  const { viewStart, viewEnd } = reverseViewWindow(
    isDesc ? readScroller().scrollTop : -readScroller().scrollTop,
    readScroller().clientHeight,
    overscanPx,
  );

  const { start, end } = getVisibleIndexRange(
    offsets,
    sizes,
    viewStart,
    viewEnd,
  );
  const { startSpacer, endSpacer } = computeSpacers(
    start,
    end,
    offsets,
    sizes,
    total,
  );

  const updateScrollFlags = useCallback(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const atNewest = isDesc
      ? isAtNewestEdge(scroller.scrollTop)
      : scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop <=
        AT_NEWEST_PX;
    atNewestRef.current = atNewest;
    const hasOverflow = scroller.scrollHeight - scroller.clientHeight > 2;
    setShowScrollToBottom(hasOverflow && !atNewest);
  }, [isDesc]);

  const handleScroll = useCallback(() => {
    updateScrollFlags();
    setScrollVersion((value) => value + 1);
    const scroller = scrollRef.current;
    if (!scroller || !onStartReached || startReachedLockRef.current) return;
    const nearOldest = isDesc
      ? isNearOldestEdge(
          scroller.scrollTop,
          scroller.scrollHeight,
          scroller.clientHeight,
        )
      : scroller.scrollTop <= NEAR_OLDEST_PX;
    if (!nearOldest) return;
    startReachedLockRef.current = true;
    onStartReached();
  }, [isDesc, onStartReached, updateScrollFlags]);

  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => {
      setScrollVersion((value) => value + 1);
    });
    observer.observe(scroller);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    updateScrollFlags();
  }, [updateScrollFlags, keys.length, heightVersion, scrollVersion]);

  const visibleItems = [];
  if (end >= start) {
    for (let index = start; index <= end; index += 1) {
      visibleItems.push(
        <MeasuredRow
          key={keys[index]}
          id={keys[index]}
          onHeight={handleHeight}
          gapBefore={index > start ? gap : 0}
        >
          {renderItem(items[index], index, index === items.length - 1)}
        </MeasuredRow>,
      );
    }
  }

  return (
    <div
      className={[
        `${prefixCls}-wrapper`,
        props.className,
        props.classNames?.wrapper,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div
        ref={scrollRef}
        className={[
          `${prefixCls}-scroll`,
          `${prefixCls}`,
          `${prefixCls}-order-${order}`,
          styles.virtualScroll,
          props.classNames?.list,
        ]
          .filter(Boolean)
          .join(" ")}
        data-testid="virtual-message-list"
        onScroll={handleScroll}
      >
        {isDesc ? <div className={`${prefixCls}-order-desc-short`} /> : null}
        {startSpacer > 0 ? (
          <div
            className={styles.spacer}
            data-testid="virtual-start-spacer"
            style={{ height: startSpacer }}
          />
        ) : null}
        {visibleItems}
        {endSpacer > 0 ? (
          <div
            className={styles.spacer}
            data-testid="virtual-end-spacer"
            style={{ height: endSpacer }}
          />
        ) : null}
      </div>
      {renderScrollToBottom?.(showScrollToBottom, scrollToBottom)}
    </div>
  );
}

const VirtualizedBubbleList = React.forwardRef(VirtualizedBubbleListInner) as <
  T extends VirtualizedItem,
>(
  props: VirtualizedBubbleListProps<T> & {
    ref?: React.Ref<VirtualizedBubbleListRef>;
  },
) => React.ReactElement;

export default VirtualizedBubbleList;
