import { describe, expect, it } from "vitest";
import type { QwenPawDataHandoff } from "./qwenpaw-host";
import { dataRouteFromHandoff } from "./App";

function handoff(): QwenPawDataHandoff {
  return {
    target_app_id: "qwenpaw-data",
    context: {
      project_ref: {
        app_id: "qwenpaw-data",
        project_id: "session/one",
        kind: "analysis-session",
      },
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
