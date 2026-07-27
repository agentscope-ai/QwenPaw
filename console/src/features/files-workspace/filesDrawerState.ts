import type { FilesDrawerEvent, FilesDrawerState } from "./types";

export const CLOSED_FILES_DRAWER: FilesDrawerState = { kind: "closed" };

export function filesDrawerReducer(
  state: FilesDrawerState,
  event: FilesDrawerEvent,
): FilesDrawerState {
  switch (event.type) {
    case "OPEN_PREVIEW":
      return {
        kind: "preview",
        target: event.target,
        trigger: event.trigger,
      };
    case "OPEN_FILES":
      return {
        kind: "workspace",
        origin: "files",
        target: event.target,
        trigger: event.trigger,
      };
    case "EXPAND_WORKSPACE":
      return state.kind === "preview"
        ? {
            kind: "workspace",
            origin: "chat",
            target: state.target,
            trigger: state.trigger,
          }
        : state;
    case "COLLAPSE_TO_PREVIEW":
      return state.kind === "workspace" && state.origin === "chat"
        ? {
            kind: "preview",
            target: state.target,
            trigger: state.trigger,
          }
        : state;
    case "CLOSE":
      return CLOSED_FILES_DRAWER;
  }
}
