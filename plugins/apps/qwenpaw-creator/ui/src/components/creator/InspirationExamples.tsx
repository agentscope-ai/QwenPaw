/** Inspiration example cards backed by OSS-hosted built-in Projects. */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { message } from "antd";
import { Loader2 } from "lucide-react";
import type { InspirationExampleSummary } from "@/contracts/creator";
import { listInspirationExamples, openInspirationExample } from "@/api/creator";
import { useRouter } from "@/routing/navigation";
import cardArt from "@/assets/design/inspiration-card-art.png";

export default function InspirationExamples() {
  const router = useRouter();
  const { t } = useTranslation();
  const [examples, setExamples] = useState<InspirationExampleSummary[]>([]);
  const [openingId, setOpeningId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listInspirationExamples()
      .then((data) => {
        if (!cancelled) setExamples(data.items ?? []);
      })
      .catch(() => {
        // No hosted examples (or an older backend): keep the section hidden.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleOpen = async (example: InspirationExampleSummary) => {
    if (openingId !== null) return;
    setOpeningId(example.id);
    try {
      const opened = await openInspirationExample(example.id);
      // No reset on success: navigation unmounts the home page, and the
      // sticky disabled state stops double-fires until that happens.
      router.push(`/project/${opened.projectId}/plan`);
    } catch {
      message.error(t("inspiration.openFailed"));
      setOpeningId(null);
    }
  };

  if (examples.length === 0) return null;
  return (
    <div className="w-full">
      <p className="mb-2 text-sm leading-6 tracking-[0.4px] text-[#808080]">
        {t("inspiration.title")}
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {examples.map((example) => (
          <button
            key={example.id}
            type="button"
            disabled={openingId !== null}
            onClick={() => void handleOpen(example)}
            className="relative cursor-pointer overflow-hidden rounded-lg border border-[#eae9e7] bg-white p-4 text-left backdrop-blur-[10px] transition-colors hover:border-[var(--color-accent)] disabled:cursor-default disabled:opacity-70"
          >
            {/* Rotated collage art from the design, clipped by the card; the
                left edge fades out so the raster never shows a seam. */}
            <img
              src={cardArt}
              alt=""
              aria-hidden
              className="pointer-events-none absolute right-0 top-0 h-full w-auto max-w-none select-none [mask-image:linear-gradient(to_right,transparent,black_35%)]"
            />
            <p className="relative z-10 flex items-center gap-2 text-sm font-medium leading-6 tracking-[0.4px] text-[#474a52]">
              {example.title}
              {openingId === example.id && (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-accent)]" />
              )}
            </p>
            <p className="relative z-10 mt-2 line-clamp-2 max-w-[62%] text-xs leading-[17px] text-[#808080]">
              {example.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
