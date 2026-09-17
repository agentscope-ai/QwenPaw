/** Inspiration example cards backed by OSS-hosted built-in Projects. */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { message } from "antd";
import { Loader2 } from "lucide-react";
import type { InspirationExampleSummary } from "@/contracts/creator";
import {
  getInspirationExampleOpenProgress,
  listInspirationExamples,
  openInspirationExample,
} from "@/api/creator";
import { useRouter } from "@/routing/navigation";
import { formatBytes } from "@/components/creator/ProjectImportExport";
import cardArt from "@/assets/design/inspiration-card-art.png";

interface OpenProgress {
  receivedBytes: number;
  totalBytes: number | null;
}

export default function InspirationExamples() {
  const router = useRouter();
  const { t } = useTranslation();
  const [examples, setExamples] = useState<InspirationExampleSummary[]>([]);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [progress, setProgress] = useState<OpenProgress | null>(null);

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

  // While an example is opening, mirror its archive download progress so the
  // card shows real movement instead of a bare spinner.
  useEffect(() => {
    if (openingId === null) return undefined;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      while (active) {
        try {
          const state = await getInspirationExampleOpenProgress(openingId);
          if (!active) return;
          if (state.state === "downloading") {
            setProgress({
              receivedBytes: state.receivedBytes ?? 0,
              totalBytes: state.totalBytes ?? null,
            });
          }
        } catch {
          // Older backend without the progress route: keep the spinner only.
        }
        await new Promise<void>((resolve) => {
          timer = setTimeout(resolve, 1000);
        });
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [openingId]);

  const handleOpen = async (example: InspirationExampleSummary) => {
    if (openingId !== null) return;
    setOpeningId(example.id);
    setProgress(null);
    try {
      const opened = await openInspirationExample(example.id);
      // No reset on success: navigation unmounts the home page, and the
      // sticky disabled state stops double-fires until that happens.
      router.push(`/project/${opened.projectId}/plan`);
    } catch {
      message.error(t("inspiration.openFailed"));
      setOpeningId(null);
      setProgress(null);
    }
  };

  if (examples.length === 0) return null;
  return (
    <div className="w-full">
      <p className="mb-2 text-sm leading-6 tracking-[0.4px] text-[#808080]">
        {t("inspiration.title")}
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {examples.map((example) => {
          const isOpening = openingId === example.id;
          return (
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
                {isOpening && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-accent)]" />
                )}
              </p>
              {isOpening ? (
                <div className="relative z-10 mt-2 max-w-[80%]">
                  <p className="text-xs leading-[17px] text-[#808080]">
                    {progress
                      ? t("inspiration.downloadingHint")
                      : t("inspiration.preparingHint")}
                  </p>
                  <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-[#eae9e7]">
                    <div
                      className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-300"
                      style={{
                        width:
                          progress &&
                          progress.totalBytes &&
                          progress.totalBytes > 0
                            ? `${Math.min(
                                100,
                                Math.round(
                                  (progress.receivedBytes /
                                    progress.totalBytes) *
                                    100,
                                ),
                              )}%`
                            : "8%",
                      }}
                    />
                  </div>
                  {progress && (
                    <p className="mt-1 text-[11px] leading-4 text-[#a3a3a3]">
                      {progress.totalBytes && progress.totalBytes > 0
                        ? `${formatBytes(
                            progress.receivedBytes,
                          )} / ${formatBytes(progress.totalBytes)}`
                        : formatBytes(progress.receivedBytes)}
                    </p>
                  )}
                </div>
              ) : (
                <p className="relative z-10 mt-2 line-clamp-2 max-w-[62%] text-xs leading-[17px] text-[#808080]">
                  {example.description}
                </p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
