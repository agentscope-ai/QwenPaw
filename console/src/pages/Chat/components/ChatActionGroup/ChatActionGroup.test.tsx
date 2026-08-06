import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";

// Mock react-window to avoid import errors in mocked ChatSessionDrawer
const { MockVariableSizeList } = vi.hoisted(() => {
  const React = require("react");
  const MockVariableSizeList = React.forwardRef((props: any, ref: any) => {
    React.useImperativeHandle(ref, () => ({
      resetAfterIndex: () => {},
    }));
    const Row = props.children;
    return (
      <>
        {Array.from({ length: props.itemCount }, (_: any, i: number) => (
          <Row key={i} index={i} style={{}} data={props.itemData} />
        ))}
      </>
    );
  });
  return { MockVariableSizeList };
});
vi.mock("react-window", () => ({
  VariableSizeList: MockVariableSizeList,
}));

vi.mock("../../ChatSessionDrawer", () => ({ default: () => null }));

import ChatActionGroup from "./index";

describe("ChatActionGroup", () => {
  it("renders without crash", () => {
    expect(() => renderWithProviders(<ChatActionGroup />)).not.toThrow();
  });

  it("renders history icon button when onToggleHistory is provided", () => {
    renderWithProviders(<ChatActionGroup onToggleHistory={() => {}} />);
    expect(
      document.querySelector('[data-icon="SparkHistoryLine"]'),
    ).toBeInTheDocument();
  });

  it("does not render history icon button in simple mode (no onToggleHistory)", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkHistoryLine"]'),
    ).not.toBeInTheDocument();
  });

  it("renders new chat icon button", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkNewChatFill"]'),
    ).toBeInTheDocument();
  });

  it("renders the Session workspace toggle next to essential actions", () => {
    const onToggleWorkspace = vi.fn();
    renderWithProviders(
      <ChatActionGroup onToggleWorkspace={onToggleWorkspace} />,
    );

    const button = document.querySelector(
      'button[aria-label="files.openWorkspace"]',
    ) as HTMLButtonElement | null;
    expect(button).toBeInTheDocument();
    expect(button).toHaveStyle({
      width: "32px",
      height: "32px",
      padding: "0px",
    });
    expect(button?.querySelector("svg")).toHaveAttribute("width", "16");
    expect(button?.querySelector("svg")).toHaveAttribute("height", "16");
    expect(button?.querySelector("svg")).toHaveStyle({
      width: "16px",
      height: "16px",
    });
    button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onToggleWorkspace).toHaveBeenCalledOnce();
  });
});
