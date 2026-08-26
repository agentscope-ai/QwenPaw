import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EditPlanCard from "@/components/timeline/EditPlanCard";
import type { EditPlanDocument } from "@/contracts/creator";

const plan: EditPlanDocument = {
  concept: "猫的越狱日记",
  dials: { energy: "high", density: "mid", decoration: "low" },
  signature_device: "爪印转场",
  pacing: "hook 1.2s，动静交替",
  design_floor: {
    opening: "1.5s 标题卡",
    transitions: "硬切 + 爪印族",
    body: "每场景一个设计节拍",
    ending: "定格硬停",
  },
  mechanical_exemption: false,
  scene_ledger: [
    {
      scene_id: "scene-1",
      label: "越狱",
      element_ids: ["el-1"],
      status: "locked",
      review_round: 1,
    },
    {
      scene_id: "scene-2",
      label: "追逐",
      element_ids: ["el-2"],
      status: "draft",
      review_round: 0,
    },
  ],
};

describe("EditPlanCard", () => {
  it("renders nothing without a plan", () => {
    const { container } = render(<EditPlanCard editPlan={null} />);
    expect(container.querySelector("[data-edit-plan-card]")).toBeNull();
  });

  it("shows the concept and the ledger lock ratio, expanding on click", () => {
    render(<EditPlanCard editPlan={plan} />);
    expect(screen.getByText("猫的越狱日记")).toBeInTheDocument();
    expect(screen.getByText(/1\/2/)).toBeInTheDocument();
    expect(screen.queryByText(/爪印转场/)).toBeNull();
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/爪印转场/)).toBeInTheDocument();
    expect(screen.getByText(/1\.5s 标题卡/)).toBeInTheDocument();
    expect(screen.getByText("越狱")).toBeInTheDocument();
    expect(screen.getByText("追逐")).toBeInTheDocument();
  });
});
