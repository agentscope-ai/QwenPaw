import { createContext } from "react";

/** Status of this response only; a later turn must not restart older tools. */
export const ToolResponseStatusContext = createContext<string | undefined>(
  undefined,
);
