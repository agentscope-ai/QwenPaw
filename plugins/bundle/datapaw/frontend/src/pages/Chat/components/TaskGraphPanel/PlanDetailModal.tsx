import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import YamlCodeEditor from "./YamlCodeEditor";
import styles from "./PlanCorrectionPopover.module.less";

interface PlanDetailModalProps {
  open: boolean;
  loading: boolean;
  yaml: string | null;
  onClose: () => void;
}

export default function PlanDetailModal({
  open,
  loading,
  yaml,
  onClose,
}: PlanDetailModalProps) {
  const { t } = useTranslation();

  return (
    <Modal
      open={open}
      title={t("taskGraph.viewPlanDetail")}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
    >
      <div className={styles.popoverPanel}>
        {loading ? (
          <p>{t("taskGraph.previewLoading")}</p>
        ) : (
          <YamlCodeEditor value={yaml ?? ""} onChange={() => {}} readOnly />
        )}
      </div>
    </Modal>
  );
}
