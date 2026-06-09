import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { CloseOutlined } from '@ant-design/icons';
import { Button, Popover } from '@agentscope-ai/design';
import { useTranslation } from 'react-i18next';
import type { PlanSnapshot } from './types';
import { planToEditableYaml } from './planToYaml';
import YamlCodeEditor from './YamlCodeEditor';
import styles from './PlanCorrectionPopover.module.less';

interface PlanCorrectionPopoverProps {
  plan: PlanSnapshot;
  children: ReactNode;
  onConfirm?: (yaml: string) => void;
}

export default function PlanCorrectionPopover({
  plan,
  children,
  onConfirm,
}: PlanCorrectionPopoverProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [yaml, setYaml] = useState(() => planToEditableYaml(plan));

  useEffect(() => {
    if (open) {
      setYaml(planToEditableYaml(plan));
    }
  }, [open, plan]);

  const handleCancel = useCallback(() => {
    setOpen(false);
  }, []);

  const handleConfirm = useCallback(() => {
    onConfirm?.(yaml);
    setOpen(false);
  }, [onConfirm, yaml]);

  const content = (
    <div className={styles.popoverPanel}>
      <div className={styles.popoverHeader}>
        <span className={styles.popoverTitle}>{t('taskGraph.planCorrection')}</span>
        <button
          type="button"
          className={styles.closeBtn}
          aria-label={t('taskGraph.close')}
          onClick={handleCancel}
        >
          <CloseOutlined />
        </button>
      </div>

      <YamlCodeEditor value={yaml} onChange={setYaml} />

      <div className={styles.popoverFooter}>
        <Button type="default" className={styles.cancelBtn} onClick={handleCancel}>
          {t('common.cancel')}
        </Button>
        <Button type="primary" className={styles.confirmBtn} onClick={handleConfirm}>
          {t('taskGraph.confirmUpdate')}
        </Button>
      </div>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      placement="rightTop"
      open={open}
      onOpenChange={setOpen}
      arrow
      autoAdjustOverflow
      overlayClassName={styles.planCorrectionPopover}
      overlayInnerStyle={{ padding: 0 }}
    >
      <span
        className={styles.triggerWrap}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </span>
    </Popover>
  );
}
