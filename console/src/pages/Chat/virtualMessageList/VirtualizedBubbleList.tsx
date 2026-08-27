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
  DEFAULT_OVERSCAN_COUNT,
  DEFAULT_OVERSCAN_PX,
  DEFAULT_ROW_GAP,
  NEAR_OLDEST_PX,
  accumulateOffsets,
  computeSpacers,
  expandIndexRange,
  getVisibleIndexRange,
  isAtNewestEdge,
  isNearOldestEdge,
  itemKey,
  reverseAnchorAt,
  reverseViewWindow,
  scrollTopForIndex,
  scrollTopForReverseAnchor,
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
  overscanCount?: number;
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
  children: React.ReactNode;
}

const MeasuredRow: React.FC<MeasuredRowProps> = ({
  id,
  onHeight,
  children,
}) => {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const report = () => {
      const height = Math.round(element.getBoundingClientRect().height);
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
    overscanCount = DEFAULT_OVERSCAN_COUNT,
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
  const oldestKey = keys.length > 0 ? keys[keys.length - 1] : null;
  const snapshotRef = useRef<{
    keys: readonly string[];
    offsets: readonly number[];
    sizes: readonly number[];
    scrollTop: number;
  }>({ keys: [], offsets: [], sizes: [], scrollTop: 0 });

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

  useLayoutEffect(() => {
    const live = new Set(keys);
    for (const key of [...heightsRef.current.keys()]) {
      if (!live.has(key)) heightsRef.current.delete(key);
    }
  }, [keys]);

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
    const scroller = scrollRef.current;
    const snapshot = snapshotRef.current;

    if (scroller && isDesc) {
      if (atNewestRef.current) {
        if (scroller.scrollTop !== 0) {
          scroller.scrollTop = 0;
          setScrollVersion((value) => value + 1);
        }
      } else if (snapshot.keys.length > 0) {
        const viewStart = Math.max(0, -snapshot.scrollTop);
        const anchor = reverseAnchorAt(
          viewStart,
          snapshot.keys,
          snapshot.offsets,
          snapshot.sizes,
        );
        const nextTop =
          anchor === null
            ? null
            : scrollTopForReverseAnchor(anchor, keys, offsets);
        if (nextTop !== null && scroller.scrollTop !== nextTop) {
          scroller.scrollTop = nextTop;
          setScrollVersion((value) => value + 1);
        }
      }
    }

    snapshotRef.current = {
      keys,
      offsets,
      sizes,
      scrollTop: scroller?.scrollTop ?? 0,
    };
  }, [isDesc, keys, offsets, sizes]);

  useEffect(() => {
    startReachedLockRef.current = false;
  }, [oldestKey]);

  const scrollerMetrics = scrollRef.current;
  const { viewStart, viewEnd } = reverseViewWindow(
    isDesc
      ? (scrollerMetrics?.scrollTop ?? 0)
      : -(scrollerMetrics?.scrollTop ?? 0),
    scrollerMetrics?.clientHeight ?? 0,
    overscanPx,
  );

  const { start: rawStart, end: rawEnd } = getVisibleIndexRange(
    offsets,
    sizes,
    viewStart,
    viewEnd,
  );
  const { start, end } = expandIndexRange(
    rawStart,
    rawEnd,
    keys.length,
    overscanCount,
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
    const scroller = scrollRef.current;
    if (scroller) {
      snapshotRef.current = {
        ...snapshotRef.current,
        scrollTop: scroller.scrollTop,
      };
    }
    updateScrollFlags();
    setScrollVersion((value) => value + 1);
    if (!scroller || !onStartReached) return;
    const nearOldest = isDesc
      ? isNearOldestEdge(
          scroller.scrollTop,
          scroller.scrollHeight,
          scroller.clientHeight,
        )
      : scroller.scrollTop <= NEAR_OLDEST_PX;
    if (!nearOldest) {
      startReachedLockRef.current = false;
      return;
    }
    if (startReachedLockRef.current) return;
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
      const isLast = isDesc ? index === 0 : index === items.length - 1;
      visibleItems.push(
        <MeasuredRow key={keys[index]} id={keys[index]} onHeight={handleHeight}>
          {renderItem(items[index], index, isLast)}
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
        {visibleItems.length > 0 ? (
          <div className={styles.rows} style={{ gap }}>
            {visibleItems}
          </div>
        ) : null}
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
