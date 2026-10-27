import { Form } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

import type { AgentSummary } from "@/api/types/agents";
import { AgentModal } from "./AgentModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: { listProviders: vi.fn().mockResolvedValue([]) },
}));

vi.mock("@/api/modules/skill", () => ({
  skillApi: {
    listSkillPoolSkills: vi.fn().mockResolvedValue([]),
    listSkills: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock("./AgentBackendFields", () => ({ AgentBackendFields: () => null }));

const EDITING_AGENT: AgentSummary = {
  id: "mail-agent",
  name: "Mail Agent",
  description: "",
  workspace_dir: "/tmp/mail-agent",
  enabled: true,
  backend: "qwenpaw",
};

const stableCallbacks = {
  onSelectedSkillsChange: vi.fn(),
  onInstalledSkillsLoaded: vi.fn(),
  onSave: vi.fn().mockResolvedValue(undefined),
  onCancel: vi.fn(),
};

function Harness({ mailMode }: { mailMode: "personal" | "dedicated" }) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({ backend: "qwenpaw", mail_mode: mailMode });
  }, [form, mailMode]);

  return (
    <AgentModal
      open
      editingAgent={EDITING_AGENT}
      form={form}
      selectedSkills={[]}
      {...stableCallbacks}
    />
  );
}

describe.each(["personal", "dedicated"] as const)(
  "AgentModal %s mail domains",
  (mailMode) => {
    it("only allows selecting an exposed preset", async () => {
      const user = userEvent.setup();
      render(<Harness mailMode={mailMode} />);

      const input = await screen.findByLabelText("agent.mailDomain");
      await user.click(input);
      expect(await screen.findByText("gmail.com")).toBeInTheDocument();
      expect(screen.queryByText("exmail.qq.com")).not.toBeInTheDocument();
      expect(screen.queryByText("qiye.aliyun.com")).not.toBeInTheDocument();
      expect(screen.queryByText("qiye.163.com")).not.toBeInTheDocument();

      expect(input).toHaveAttribute("readonly");
      await user.type(input, "exmail.qq.com");
      expect(input).not.toHaveValue("exmail.qq.com");
    });
  },
);

describe("AgentModal dedicated mailbox credential", () => {
  it("shows one optional provider credential and no registration secrets", async () => {
    render(<Harness mailMode="dedicated" />);

    const credential = await screen.findByLabelText(
      "agent.mailAuthCodeOptional",
    );
    expect(credential).not.toHaveAttribute("aria-required", "true");
    expect(
      screen.queryByLabelText("agent.mailPassword"),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("agent.mailPhone")).not.toBeInTheDocument();
  });

  it("requires the final mailbox name after a credential is entered", async () => {
    const user = userEvent.setup();
    render(<Harness mailMode="dedicated" />);

    await user.type(
      await screen.findByLabelText("agent.mailAuthCodeOptional"),
      "abcdefghijklmnop",
    );

    expect(screen.getByLabelText("agent.mailNameDedicated")).toHaveAttribute(
      "aria-required",
      "true",
    );
  });

  it("uses the provider password label for Aliyun Mail", async () => {
    const user = userEvent.setup();
    render(<Harness mailMode="dedicated" />);

    await user.click(await screen.findByLabelText("agent.mailDomain"));
    await user.click(await screen.findByText("aliyun.com"));

    expect(
      await screen.findByLabelText("agent.mailCredentialOptional"),
    ).toBeInTheDocument();
  });
});
