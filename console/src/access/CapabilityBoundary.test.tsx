import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useAuthStore } from "../stores/authStore";
import { Capability } from "./capabilities";
import CapabilityBoundary from "./CapabilityBoundary";

afterEach(() => {
  useAuthStore.getState().reset();
});

describe("CapabilityBoundary", () => {
  it("renders a 403 boundary instead of an admin page for a member", () => {
    useAuthStore.setState({
      phase: "authenticated",
      mode: "multi_user",
      user: {
        id: "member-id",
        username: "member",
        platform_role: "member",
        status: "active",
      },
    });

    render(
      <CapabilityBoundary capability={Capability.UsersManage}>
        <div>secret admin page</div>
      </CapabilityBoundary>,
    );

    expect(screen.getByText("403")).toBeInTheDocument();
    expect(screen.queryByText("secret admin page")).not.toBeInTheDocument();
  });

  it("renders the protected page for an admin", () => {
    useAuthStore.setState({
      phase: "authenticated",
      mode: "multi_user",
      user: {
        id: "admin-id",
        username: "admin",
        platform_role: "admin",
        status: "active",
      },
    });

    render(
      <CapabilityBoundary capability={Capability.UsersManage}>
        <div>admin page</div>
      </CapabilityBoundary>,
    );

    expect(screen.getByText("admin page")).toBeInTheDocument();
  });
});
