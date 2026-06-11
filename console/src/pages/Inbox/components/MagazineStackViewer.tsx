import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { HarvestInstance } from "../types";
import { generateMockHistory } from "../hooks/useMockHarvestContent";
import styles from "./MagazineStackViewer.module.less";

interface MagazineStackViewerProps {
  open: boolean;
  harvest: HarvestInstance;
  onClose: () => void;
}

export function MagazineStackViewer({
  open,
  harvest,
  onClose,
}: MagazineStackViewerProps) {
  const magazines = useMemo(
    () => generateMockHistory(harvest.name),
    [harvest.name],
  );
  const [currentIndex, setCurrentIndex] = useState(0);
  const current = magazines[currentIndex];

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose();
      }}
    >
      <DialogContent className="max-w-[1100px] w-full">
        <DialogHeader>
          <DialogTitle>{harvest.name} · History</DialogTitle>
        </DialogHeader>

        <div className={cn("flex gap-4 mt-2", styles.viewerContainer)}>
          <div
            className={cn(
              "flex items-center gap-3 flex-1 min-w-0",
              styles.mainArea,
            )}
          >
            <Button
              variant="outline"
              size="icon"
              className="shrink-0"
              disabled={currentIndex === 0}
              onClick={() => setCurrentIndex((prev) => Math.max(prev - 1, 0))}
            >
              <ChevronLeft size={18} />
            </Button>

            <Card className={cn("flex-1 min-w-0", styles.contentCard)}>
              <CardContent className="p-5">
                <h3 className="text-base font-semibold text-foreground mb-1">
                  {current.title}
                </h3>
                <p className="text-xs text-muted-foreground mb-3">
                  {current.date.toLocaleDateString()}
                </p>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {current.content}
                </p>
              </CardContent>
            </Card>

            <Button
              variant="outline"
              size="icon"
              className="shrink-0"
              disabled={currentIndex === magazines.length - 1}
              onClick={() =>
                setCurrentIndex((prev) =>
                  Math.min(prev + 1, magazines.length - 1),
                )
              }
            >
              <ChevronRight size={18} />
            </Button>
          </div>

          <div
            className={cn(
              "flex flex-col gap-1 w-36 overflow-y-auto max-h-[420px] shrink-0",
              styles.timeline,
            )}
          >
            {magazines.map((mag, index) => (
              <button
                key={mag.id}
                className={cn(
                  "text-left text-xs px-2.5 py-2 rounded-md transition-colors",
                  index === currentIndex
                    ? "bg-orange-500 text-white font-medium"
                    : "text-muted-foreground hover:bg-muted",
                  styles.timelineItem,
                  index === currentIndex && styles.active,
                )}
                onClick={() => setCurrentIndex(index)}
              >
                <span>{mag.date.toLocaleDateString()}</span>
              </button>
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
