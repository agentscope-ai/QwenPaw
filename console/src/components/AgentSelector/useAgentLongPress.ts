import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
} from "react";

import type { AgentSummary } from "../../api/types/agents";

const LONG_PRESS_MS = 500;
const MOVE_TOLERANCE_PX = 8;
const FEEDBACK_MS = 520;

interface PressOrigin {
  agentId: string;
  pointerId: number;
  x: number;
  y: number;
}

export function useAgentLongPress(onLongPress: (agent: AgentSummary) => void) {
  const timerRef = useRef<number | null>(null);
  const feedbackTimerRef = useRef<number | null>(null);
  const originRef = useRef<PressOrigin | null>(null);
  const suppressClickRef = useRef<string | null>(null);
  const [pressingId, setPressingId] = useState<string | null>(null);
  const [feedbackId, setFeedbackId] = useState<string | null>(null);

  const clearPress = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    originRef.current = null;
    setPressingId(null);
  }, []);

  useEffect(
    () => () => {
      clearPress();
      if (feedbackTimerRef.current !== null) {
        window.clearTimeout(feedbackTimerRef.current);
      }
    },
    [clearPress],
  );

  const showFeedback = useCallback((agentId: string) => {
    setFeedbackId(agentId);
    if (feedbackTimerRef.current !== null) {
      window.clearTimeout(feedbackTimerRef.current);
    }
    feedbackTimerRef.current = window.setTimeout(() => {
      setFeedbackId(null);
      feedbackTimerRef.current = null;
    }, FEEDBACK_MS);
  }, []);

  const trigger = useCallback(
    (agent: AgentSummary) => {
      if (agent.id === "default") return;
      suppressClickRef.current = agent.id;
      clearPress();
      showFeedback(agent.id);
      onLongPress(agent);
    },
    [clearPress, onLongPress, showFeedback],
  );

  const getLongPressProps = useCallback(
    (agent: AgentSummary) => ({
      tabIndex: 0,
      onPointerDown: (event: PointerEvent<HTMLDivElement>) => {
        if (
          agent.id === "default" ||
          event.button !== 0 ||
          (event.target as HTMLElement).closest("button")
        ) {
          return;
        }
        clearPress();
        originRef.current = {
          agentId: agent.id,
          pointerId: event.pointerId,
          x: event.clientX,
          y: event.clientY,
        };
        setPressingId(agent.id);
        timerRef.current = window.setTimeout(() => {
          trigger(agent);
        }, LONG_PRESS_MS);
      },
      onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
        const origin = originRef.current;
        if (!origin || origin.pointerId !== event.pointerId) return;
        const moved = Math.hypot(
          event.clientX - origin.x,
          event.clientY - origin.y,
        );
        if (moved > MOVE_TOLERANCE_PX) clearPress();
      },
      onPointerUp: clearPress,
      onPointerCancel: clearPress,
      onPointerLeave: (event: PointerEvent<HTMLDivElement>) => {
        if (event.pointerType === "mouse") clearPress();
      },
      onClickCapture: (event: MouseEvent<HTMLDivElement>) => {
        if (suppressClickRef.current !== agent.id) return;
        event.preventDefault();
        event.stopPropagation();
        suppressClickRef.current = null;
      },
    }),
    [clearPress, trigger],
  );

  return { getLongPressProps, pressingId, feedbackId };
}
