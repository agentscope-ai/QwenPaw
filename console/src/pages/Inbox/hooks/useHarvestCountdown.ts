import { useEffect, useState } from "react";

interface CountdownResult {
  hours: number;
  minutes: number;
  seconds: number;
  percentage: number;
  isOverdue: boolean;
}

export function useHarvestCountdown(nextRun: Date): CountdownResult {
  const [countdown, setCountdown] = useState<CountdownResult>({
    hours: 0,
    minutes: 0,
    seconds: 0,
    percentage: 0,
    isOverdue: false,
  });

  useEffect(() => {
    const calculate = () => {
      const now = Date.now();
      const target = nextRun.getTime();
      const diff = target - now;
      if (diff <= 0) {
        setCountdown({
          hours: 0,
          minutes: 0,
          seconds: 0,
          percentage: 100,
          isOverdue: true,
        });
        return;
      }
      const totalSeconds = Math.floor(diff / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      const daySeconds = 24 * 60 * 60;
      const percentage = Math.min(
        100,
        Math.max(0, ((daySeconds - totalSeconds) / daySeconds) * 100),
      );
      setCountdown({
        hours,
        minutes,
        seconds,
        percentage,
        isOverdue: false,
      });
    };

    calculate();
    const interval = window.setInterval(calculate, 1000);
    return () => window.clearInterval(interval);
  }, [nextRun]);

  return countdown;
}
