import { createContext, useContext, useRef } from "react";
import type { SettingsSearchTarget } from "@/plugins/settingsSearch";
import { useSettingsSearchTarget } from "./useSettingsSearchTarget";

export const SettingsSearchRequest = createContext<SettingsSearchTarget | null>(
  null,
);

export function useSettingsSearchRequest(page: string) {
  const request = useContext(SettingsSearchRequest);
  return request?.page === page ? request : null;
}

/** Retry targeting when a portalled settings surface is opened later. */
export function useSettingsSearchSurface(page: string, open: boolean) {
  const request = useSettingsSearchRequest(page);
  const body = useRef<HTMLElement>(document.body);
  useSettingsSearchTarget(body, open ? request : null, page);
  return request;
}
