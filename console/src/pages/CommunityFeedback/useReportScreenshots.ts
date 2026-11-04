import { useEffect, useRef, useState } from "react";
import { readReportScreenshot } from "./reportPrivacy";

export interface ReportImage {
  id: string;
  source: string;
  value: string;
}

/** Clipboard and file input share local validation; no image is uploaded here. */
export function useReportScreenshots(owner?: string) {
  const [images, setImages] = useState<ReportImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);
  const pending = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      generation.current += 1;
    };
  }, []);
  useEffect(() => {
    generation.current += 1;
    pending.current = false;
    setImages([]);
    setLoading(false);
    setError("");
  }, [owner]);

  useEffect(() => setError(""), [images]);

  const add = async (files: File[]) => {
    if (pending.current || !files.length) return;
    if (images.length + files.length > 2) {
      setError("communityAssist.imageLimit");
      return;
    }
    pending.current = true;
    const current = generation.current;
    setLoading(true);
    setError("");
    try {
      const next = await Promise.all(
        files.map(async (file) => {
          const value = await readReportScreenshot(file);
          return { id: crypto.randomUUID(), source: value, value };
        }),
      );
      if (active.current && current === generation.current)
        setImages((previous) => [...previous, ...next]);
    } catch {
      if (active.current && current === generation.current)
        setError("communityReport.invalidImage");
    } finally {
      if (active.current && current === generation.current) {
        pending.current = false;
        setLoading(false);
      }
    }
  };
  return { images, setImages, loading, error, add };
}
export type ReportScreenshots = ReturnType<typeof useReportScreenshots>;
