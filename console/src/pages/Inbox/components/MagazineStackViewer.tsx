import { useMemo, useState } from "react";
import { Modal, Button, Card } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
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
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={1100}
      title={`${harvest.name} · History`}
      destroyOnClose
    >
      <div className={styles.viewerContainer}>
        <div className={styles.mainArea}>
          <Button
            icon={<ChevronLeft size={18} />}
            disabled={currentIndex === 0}
            onClick={() => setCurrentIndex((prev) => Math.max(prev - 1, 0))}
          />
          <Card className={styles.contentCard}>
            <h3>{current.title}</h3>
            <p className={styles.date}>{current.date.toLocaleDateString()}</p>
            <p>{current.content}</p>
          </Card>
          <Button
            icon={<ChevronRight size={18} />}
            disabled={currentIndex === magazines.length - 1}
            onClick={() =>
              setCurrentIndex((prev) =>
                Math.min(prev + 1, magazines.length - 1),
              )
            }
          />
        </div>
        <div className={styles.timeline}>
          {magazines.map((mag, index) => (
            <button
              key={mag.id}
              className={`${styles.timelineItem} ${
                index === currentIndex ? styles.active : ""
              }`}
              onClick={() => setCurrentIndex(index)}
            >
              <span>{mag.date.toLocaleDateString()}</span>
            </button>
          ))}
        </div>
      </div>
    </Modal>
  );
}
