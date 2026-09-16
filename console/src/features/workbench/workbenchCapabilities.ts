import { Files, GitBranch, SquareTerminal, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { WorkbenchCapabilityId } from "./workbenchPreferences";

export interface WorkbenchCapability {
  id: WorkbenchCapabilityId;
  labelKey: string;
  icon: LucideIcon;
  preferredPlacement: "right" | "bottom";
}

export const WORKBENCH_CAPABILITIES: WorkbenchCapability[] = [
  {
    id: "files",
    labelKey: "workbench.files",
    icon: Files,
    preferredPlacement: "right",
  },
  {
    id: "changes",
    labelKey: "workbench.changes",
    icon: GitBranch,
    preferredPlacement: "right",
  },
  {
    id: "terminal",
    labelKey: "workbench.terminal",
    icon: SquareTerminal,
    preferredPlacement: "bottom",
  },
  {
    id: "tools",
    labelKey: "workbench.tools",
    icon: Wrench,
    preferredPlacement: "right",
  },
];

export function getWorkbenchCapability(
  id: WorkbenchCapabilityId,
): WorkbenchCapability {
  return WORKBENCH_CAPABILITIES.find((capability) => capability.id === id)!;
}
