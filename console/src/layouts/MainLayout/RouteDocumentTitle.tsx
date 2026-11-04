import { useLayoutEffect } from "react";
import { useConsoleTitlePreference } from "@/utils/consoleTitlePreference";

export function RouteDocumentTitle({ title }: { title: string }) {
  const customTitle = useConsoleTitlePreference();

  useLayoutEffect(() => {
    const nextTitle =
      customTitle.trim() ||
      (title === "QwenPaw" ? title : `${title} · QwenPaw`);
    document.title = nextTitle;
    document.dispatchEvent(
      new CustomEvent("qwenpaw:document-title-change", {
        detail: nextTitle,
      }),
    );
  }, [customTitle, title]);

  return null;
}
