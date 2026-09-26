import { createContext, useContext } from "react";

/** Notify the settings owner after programmatic user edits. */
export const ConfigAutoSaveContext = createContext<() => void>(() => {});
export const useConfigAutoSave = () => useContext(ConfigAutoSaveContext);
