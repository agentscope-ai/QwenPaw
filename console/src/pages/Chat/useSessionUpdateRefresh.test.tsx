import { act, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";
import {
  dispatchSessionUpdated,
  getSessionIdFromPushMessage,
} from "../../events/sessionUpdate";
import { useSessionUpdateRefresh } from "./useSessionUpdateRefresh";

function Harness({ chatId }: { chatId: string | null }) {
  const chatIdRef = useRef(chatId);
  chatIdRef.current = chatId;
  const [refreshKey, setRefreshKey] = useState(0);
  useSessionUpdateRefresh(chatIdRef, setRefreshKey);
  return <div data-testid="refresh-key">{refreshKey}</div>;
}

describe("useSessionUpdateRefresh", () => {
  it("extracts session update push message ids", () => {
    expect(getSessionIdFromPushMessage("session_updated:wecom:user1")).toBe(
      "wecom:user1",
    );
    expect(getSessionIdFromPushMessage("cron message")).toBeNull();
    expect(getSessionIdFromPushMessage("session_updated:")).toBeNull();
  });

  it("refreshes only when the updated session is currently open", () => {
    render(<Harness chatId="wecom:user1" />);

    expect(screen.getByTestId("refresh-key")).toHaveTextContent("0");

    act(() => {
      dispatchSessionUpdated("wecom:other");
    });

    expect(screen.getByTestId("refresh-key")).toHaveTextContent("0");

    act(() => {
      dispatchSessionUpdated("wecom:user1");
    });

    expect(screen.getByTestId("refresh-key")).toHaveTextContent("1");
  });
});
