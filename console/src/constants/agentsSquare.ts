import type { AgentsSquareSourceSpec } from "../api/types/agents";

export const DEFAULT_AGENTS_SQUARE_SOURCES: AgentsSquareSourceSpec[] = [
  {
    id: "agency-agents-zh",
    name: "agency-agents-zh",
    type: "git",
    provider: "agency_markdown_repo",
    url: "https://github.com/jnMetaCode/agency-agents-zh",
    branch: "main",
    path: ".",
    enabled: true,
    order: 1,
    trust: "community",
    license_hint: "",
    pinned: true,
  },
  {
    id: "agency-agents",
    name: "agency-agents",
    type: "git",
    provider: "agency_markdown_repo",
    url: "https://github.com/msitarzewski/agency-agents.git",
    branch: "main",
    path: ".",
    enabled: false,
    order: 2,
    trust: "official",
    license_hint: "MIT",
    pinned: true,
  },
  {
    id: "agent-teams",
    name: "agent-teams",
    type: "git",
    provider: "agency_markdown_repo",
    url: "https://github.com/dsclca12/agent-teams",
    branch: "main",
    path: ".",
    enabled: false,
    order: 3,
    trust: "community",
    license_hint: "",
    pinned: true,
  },
];

export function createDefaultAgentsSquareSources(): AgentsSquareSourceSpec[] {
  return DEFAULT_AGENTS_SQUARE_SOURCES.map((item) => ({ ...item }));
}
