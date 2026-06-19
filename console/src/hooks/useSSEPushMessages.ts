import { useEffect, useRef } from "react";

/**
 * Hook: SSE consumer for /api/console/events.
 * Plays a Web Audio beep on each push message.
 * Calls onMessage(text) when a new message arrives.
 *
 * ponytail: EventSource is native browser API (0 deps).
 * ceiling: if SSE becomes too slow/expensive, swap for WebSocket.
 */
export function useSSEPushMessages({
  playBeep = false,
  onMessage,
}: {
  playBeep?: boolean;
  onMessage?: (text: string) => void;
}) {
  const beepRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (playBeep) {
      // Use Web Audio API — 0 deps, works offline
      beepRef.current = createBeep();
    }

    const es = new EventSource("/api/console/events");

    es.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as Record<string, unknown>;
        const text = String(data.text ?? "");
        if (!text) return;

        if (playBeep && beepRef.current) {
          beepRef.current.play().catch(() => {});
        }

        onMessage?.(text);
      } catch {
        // heartbeat or malformed — ignore
      }
    };

    es.onerror = () => {
      // EventSource auto-reconnects — no action needed
    };

    return () => {
      es.close();
    };
  }, [playBeep, onMessage]);
}

function createBeep(): HTMLAudioElement | null {
  try {
    // 520Hz sine wave, 250ms
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 520;
    const gain = ctx.createGain();
    gain.gain.value = 0.3;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(0);
    osc.stop(ctx.currentTime + 0.25);

    // Build a blob URL from the generated buffer for re-use
    return {
      play: () =>
        new Promise<void>((resolve) => {
          const ctx2 = new AudioContext();
          const osc2 = ctx2.createOscillator();
          osc2.type = "sine";
          osc2.frequency.value = 520;
          const gain2 = ctx2.createGain();
          gain2.gain.value = 0.3;
          osc2.connect(gain2);
          gain2.connect(ctx2.destination);
          osc2.start(0);
          osc2.stop(ctx2.currentTime + 0.25);
          setTimeout(resolve, 280);
        }),
    } as HTMLAudioElement;
  } catch {
    return null;
  }
}
