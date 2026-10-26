import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ModelPolicy } from "../../../api/modules/hubGovernance";
import OrganizationModels from "./OrganizationModels";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));

vi.mock("../../../api/modules/hubGovernance", () => ({
  governanceRequest: request,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { name?: string }) =>
      values?.name ? `${key} ${values.name}` : key,
    i18n: { language: "en" },
  }),
}));
vi.mock("./ModelUsage", () => ({ default: () => null }));

let policy: ModelPolicy;
let enabled: boolean;
let failSave: boolean;

beforeEach(() => {
  request.mockReset();
  policy = {
    gateway_timeout_seconds: 900,
    default_model_id: null,
    member_token_limit: null,
    timezone: "UTC",
    revision: 1,
  };
  enabled = true;
  failSave = false;
  request.mockImplementation(
    async (path: string, method = "GET", body?: unknown) => {
      if (path === "admin/model-policy") {
        if (method === "PUT") {
          if (failSave) throw new Error("Save failed");
          policy = { ...(body as ModelPolicy), revision: policy.revision + 1 };
        }
        return { ...policy };
      }
      if (path === "admin/model-connections") {
        return [{ id: "provider", name: "Provider", enabled: true }];
      }
      if (path === "admin/models") {
        return ["A", "B"].map((name) => ({
          id: name,
          name: `Model ${name}`,
          upstream_model: `model-${name}`,
          connection_id: "provider",
          enabled: name === "A" || enabled,
          all_members: true,
          user_ids: [],
          input_token_limit: 4096,
          output_token_limit: 256,
          revision: 1,
        }));
      }
      if (path === "admin/models/B" && method === "PUT") {
        enabled = false;
        return {};
      }
      return path === "admin/usage" ? { members: [] } : [];
    },
  );
});

async function renderModels() {
  render(
    <App>
      <OrganizationModels />
    </App>,
  );
  const input = await screen.findByRole("spinbutton", {
    name: "hub.governance.models.gatewayTimeout",
  });
  await waitFor(() => expect(input).toHaveValue("900"));
  return input;
}

async function toggleModel() {
  const toggle = screen.getByRole("switch", {
    name: "hub.governance.models.toggleModel Model B",
  });
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).not.toBeChecked());
}

function save() {
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
}

function refresh() {
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
}

describe("Hub model policy drafts", () => {
  it("keeps the timeout draft while refreshing the policy revision", async () => {
    const input = await renderModels();
    fireEvent.change(input, { target: { value: "1200" } });
    policy = { ...policy, revision: 2, member_token_limit: 10000 };

    await toggleModel();

    expect(input).toHaveValue("1200");
    save();
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith("admin/model-policy", "PUT", {
        ...policy,
        revision: 2,
        gateway_timeout_seconds: 1200,
      }),
    );
  });

  it("preserves a failed save through a later model refresh", async () => {
    const input = await renderModels();
    fireEvent.change(input, { target: { value: "1200" } });
    failSave = true;
    save();
    await screen.findByText("Save failed");

    await toggleModel();

    expect(input).toHaveValue("1200");
  });

  it("refreshes untouched fields and clears drafts after a successful save", async () => {
    const input = await renderModels();
    policy = { ...policy, gateway_timeout_seconds: 1800, revision: 2 };
    refresh();
    await waitFor(() => expect(input).toHaveValue("1800"));

    fireEvent.change(input, { target: { value: "1200" } });
    save();
    await screen.findByText("hub.governance.models.settingsSaved");
    policy = { ...policy, gateway_timeout_seconds: 2100, revision: 4 };
    refresh();

    await waitFor(() => expect(input).toHaveValue("2100"));
  });

  it("preserves a default-model draft while refreshing an untouched timeout", async () => {
    const input = await renderModels();
    const picker = screen.getByRole("button", {
      name: "hub.governance.models.defaultModel",
    });
    fireEvent.click(picker);
    fireEvent.click(
      await screen.findByRole("button", { name: "Model B · Provider" }),
    );
    policy = { ...policy, gateway_timeout_seconds: 1800, revision: 2 };

    refresh();

    await waitFor(() => expect(input).toHaveValue("1800"));
    expect(picker).toHaveTextContent("Model B · Provider");
    save();
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        "admin/model-policy",
        "PUT",
        expect.objectContaining({
          default_model_id: "B",
          gateway_timeout_seconds: 1800,
          revision: 2,
        }),
      ),
    );
  });
});
