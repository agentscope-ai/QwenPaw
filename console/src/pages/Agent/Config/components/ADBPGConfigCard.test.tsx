import { Form } from "@agentscope-ai/design";
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ADBPGConfigCard,
  createDefaultADBPGMemoryConfig,
} from "./ADBPGConfigCard";

vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);

describe("ADBPGConfigCard defaults", () => {
  it("creates the complete backend default structure for an unconfigured agent", () => {
    expect(createDefaultADBPGMemoryConfig()).toEqual({
      rest_base_url: "",
      rest_api_key: "",
      memory_isolation: true,
      search_timeout: 10,
      auto_memory_search_config: {
        enabled: true,
        max_results: 3,
      },
    });
  });

  it("initializes the complete object when the backend has no saved config", async () => {
    let current: unknown;
    function Harness() {
      const [form] = Form.useForm();
      current = Form.useWatch("adbpg_memory_config", form);
      return (
        <Form form={form}>
          <ADBPGConfigCard />
        </Form>
      );
    }

    render(<Harness />);

    await waitFor(() =>
      expect(current).toEqual({
        rest_base_url: "",
        rest_api_key: "",
        memory_isolation: true,
        search_timeout: 10,
        auto_memory_search_config: {
          enabled: true,
          max_results: 3,
        },
      }),
    );
  });
});
