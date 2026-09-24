import { describe, expect, it } from "vitest";
import type { PawHandoffRequest } from "../../../../../console/src/plugins/pawapp-sdk/types";
import { dataRouteFromHandoff } from "./App";

function handoff(): PawHandoffRequest {
  return {
    schema_version: 1,
    handoff_id: "handoff-1",
    source_app_id: "qwenpaw-data",
    target_app_id: "qwenpaw-data",
    created_at: 1,
    context: {
      schema_version: 1,
      context_id: "context-1",
      revision: 1,
      task_id: "task-1",
      goal: "Analyze revenue",
      scope: {
        workspace_id: "sales",
        source_app_id: "qwenpaw-data",
        action_id: "analyze",
        engagement: "delegated",
      },
      artifact_refs: [],
      decision_refs: [],
      project_ref: {
        schema_version: 1,
        app_id: "qwenpaw-data",
        project_id: "session/one",
        kind: "analysis-session",
        revision: 1,
      },
      resume_ref: "task-1",
    },
  };
}

describe("QwenPaw Data handoffs", () => {
  it("opens the existing engine session without creating another run", () => {
    expect(dataRouteFromHandoff(handoff())).toBe(
      "/console?session_id=session%2Fone",
    );
  });

  it("passes the declared App view as an opaque workspace hint", () => {
    const value = handoff();
    value.context.view_id = "evidence";
    expect(dataRouteFromHandoff(value)).toBe(
      "/console?session_id=session%2Fone&paw_view=evidence",
    );
  });

  it("rejects projects owned by another App", () => {
    const value = handoff();
    value.context.project_ref.app_id = "creator";
    expect(() => dataRouteFromHandoff(value)).toThrow(
      "unsupported_data_handoff",
    );
  });
});
