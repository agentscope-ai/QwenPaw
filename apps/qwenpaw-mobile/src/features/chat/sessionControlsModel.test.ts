import assert from "node:assert/strict";
import test from "node:test";

import {
  applyLoopModeCommand,
  normalizeLoopModes,
  selectableProviders,
} from "./sessionControlsModel";

test("loop command is added once and preserves explicit slash commands", () => {
  const goal = {
    id: "goal",
    name: "Goal",
    slash_command: "goal",
    description: "",
    source: "builtin" as const,
  };
  assert.equal(applyLoopModeCommand("finish this", goal), "/goal finish this");
  assert.equal(applyLoopModeCommand("/goal finish this", goal), "/goal finish this");
  assert.equal(applyLoopModeCommand("/compact", goal), "/compact");
});

test("loop catalog always contains one default mode", () => {
  const modes = normalizeLoopModes([]);
  assert.deepEqual(modes.map((mode) => mode.id), ["default"]);
});

test("model list excludes disconnected providers and duplicate models", () => {
  const providers = selectableProviders([
    {
      id: "ready",
      name: "Ready",
      api_key: "configured",
      base_url: "https://example.com",
      models: [{ id: "m1", name: "One" }],
      extra_models: [{ id: "m1", name: "Duplicate" }],
      is_custom: false,
      is_local: false,
      require_api_key: true,
    },
    {
      id: "missing",
      name: "Missing",
      api_key: "",
      base_url: "https://example.com",
      models: [{ id: "m2", name: "Two" }],
      extra_models: [],
      is_custom: false,
      is_local: false,
      require_api_key: true,
    },
  ]);
  assert.deepEqual(providers.map((provider) => provider.id), ["ready"]);
  assert.deepEqual(providers[0]?.models.map((model) => model.id), ["m1"]);
});

test("unconfigured free-tier providers expose no models", () => {
  const providers = selectableProviders([
    {
      id: "free-tier",
      name: "Free Tier",
      api_key: "",
      base_url: "https://example.com",
      models: [
        { id: "free", name: "Free", is_free: true },
        { id: "paid", name: "Paid", is_free: false },
      ],
      extra_models: [],
      is_custom: false,
      is_local: false,
      require_api_key: true,
      is_free_tier: true,
    },
  ]);

  assert.deepEqual(providers, []);
});

test("configured free-tier providers expose free and paid models", () => {
  const providers = selectableProviders([
    {
      id: "free-tier",
      name: "Free Tier",
      api_key: "configured",
      base_url: "https://example.com",
      models: [
        { id: "free", name: "Free", is_free: true },
        { id: "paid", name: "Paid", is_free: false },
      ],
      extra_models: [],
      is_custom: false,
      is_local: false,
      require_api_key: true,
      is_free_tier: true,
    },
  ]);

  assert.deepEqual(
    providers[0]?.models.map((model) => model.id),
    ["free", "paid"],
  );
});

test("custom and keyless providers require a base URL", () => {
  const providers = selectableProviders([
    {
      id: "custom-missing-url",
      name: "Custom Missing URL",
      api_key: "configured",
      base_url: "",
      models: [{ id: "custom-hidden", name: "Custom Hidden" }],
      extra_models: [],
      is_custom: true,
      is_local: false,
      require_api_key: true,
    },
    {
      id: "custom-ready",
      name: "Custom Ready",
      api_key: "",
      base_url: "https://custom.example.com",
      models: [{ id: "custom", name: "Custom" }],
      extra_models: [],
      is_custom: true,
      is_local: false,
      require_api_key: true,
    },
    {
      id: "keyless-missing-url",
      name: "Keyless Missing URL",
      api_key: "",
      base_url: "",
      models: [{ id: "keyless-hidden", name: "Keyless Hidden" }],
      extra_models: [],
      is_custom: false,
      is_local: false,
      require_api_key: false,
    },
    {
      id: "keyless-ready",
      name: "Keyless Ready",
      api_key: "",
      base_url: "https://keyless.example.com",
      models: [{ id: "keyless", name: "Keyless" }],
      extra_models: [],
      is_custom: false,
      is_local: false,
      require_api_key: false,
    },
  ]);

  assert.deepEqual(
    providers.map((provider) => provider.id),
    ["custom-ready", "keyless-ready"],
  );
});

test("candidate models are isolated by each QwenPaw configuration", () => {
  const configured = selectableProviders([
    {
      id: "provider",
      name: "Provider",
      api_key: "configured",
      base_url: "https://example.com",
      models: [{ id: "model", name: "Model" }],
      extra_models: [],
      is_custom: false,
      is_local: false,
      require_api_key: true,
    },
  ]);
  const unconfigured = selectableProviders([
    {
      id: "provider",
      name: "Provider",
      api_key: "",
      base_url: "https://example.com",
      models: [{ id: "model", name: "Model" }],
      extra_models: [],
      is_custom: false,
      is_local: false,
      require_api_key: true,
    },
  ]);

  assert.deepEqual(configured.map((provider) => provider.id), ["provider"]);
  assert.deepEqual(unconfigured, []);
});
