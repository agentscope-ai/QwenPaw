import { createContext } from "react";

/** CoPaw's durable regenerate operation, scoped to the mounted Chat. */
export const ChatRegenerateContext = createContext<
  ((responseMessageId: string) => void) | undefined
>(undefined);
