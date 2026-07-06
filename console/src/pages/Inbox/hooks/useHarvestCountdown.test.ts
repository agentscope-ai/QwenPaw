/**
 * Tests for useHarvestCountdown hook.
 *
 * Covers:
 * - nextRun already in the past -> isOverdue true, percentage 100, zeroed h/m/s
 * - normal countdown decomposition (hours/minutes/seconds)
 * - sub-minute countdown
 * - percentage lower bound when totalSeconds equals one day
 * - setInterval fires every second, decrementing remaining seconds
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useHarvestCountdown } from "./useHarvestCountdown";

// Fixed baseline: 2026-01-01T00:00:00.000Z
const BASELINE = new Date("2026-01-01T00:00:00.000Z");

describe("useHarvestCountdown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASELINE);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("marks overdue when nextRun is in the past", () => {
    const past = new Date(BASELINE.getTime() - 1000);
    const { result } = renderHook(() => useHarvestCountdown(past));

    expect(result.current.isOverdue).toBe(true);
    expect(result.current.percentage).toBe(100);
    expect(result.current.hours).toBe(0);
    expect(result.current.minutes).toBe(0);
    expect(result.current.seconds).toBe(0);
  });

  it("decomposes 3h30m remaining into hours, minutes, seconds", () => {
    // 12600 seconds = 3*3600 + 30*60
    const nextRun = new Date(BASELINE.getTime() + 12600 * 1000);
    const { result } = renderHook(() => useHarvestCountdown(nextRun));

    expect(result.current.isOverdue).toBe(false);
    expect(result.current.hours).toBe(3);
    expect(result.current.minutes).toBe(30);
    expect(result.current.seconds).toBe(0);
  });

  it("decomposes 65 seconds remaining into minutes and seconds", () => {
    const nextRun = new Date(BASELINE.getTime() + 65 * 1000);
    const { result } = renderHook(() => useHarvestCountdown(nextRun));

    expect(result.current.hours).toBe(0);
    expect(result.current.minutes).toBe(1);
    expect(result.current.seconds).toBe(5);
  });

  it("clamps percentage to 0 when totalSeconds equals one day", () => {
    // 86400 seconds = exactly 24h; daySeconds - totalSeconds = 0 -> percentage 0
    const nextRun = new Date(BASELINE.getTime() + 86400 * 1000);
    const { result } = renderHook(() => useHarvestCountdown(nextRun));

    expect(result.current.percentage).toBe(0);
    expect(result.current.hours).toBe(24);
    expect(result.current.isOverdue).toBe(false);
  });

  it("decrements remaining seconds each interval tick", () => {
    const nextRun = new Date(BASELINE.getTime() + 10 * 1000);
    const { result } = renderHook(() => useHarvestCountdown(nextRun));

    expect(result.current.seconds).toBe(10);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.seconds).toBe(9);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.seconds).toBe(8);
  });
});
