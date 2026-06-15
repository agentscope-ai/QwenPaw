import { useTranslation } from 'react-i18next';
import type { TaskNode } from './types';
import styles from './TaskNodeDrawer.module.less';

export interface CompletedNodeContentProps {
  node: TaskNode;
}

/** Static result view for finished nodes — no live-stream styling. */
export default function CompletedNodeContent({ node }: CompletedNodeContentProps) {
  const { t } = useTranslation();
  const output = node.output;
  const summary = output?.summary || node.outcome;
  const reasoning = output?.reasoning;
  const error = node.error;
  const hasContent = Boolean(summary || reasoning || error);

  if (!hasContent) {
    return <div className={styles.emptyState}>{t('taskGraph.noTrace')}</div>;
  }

  return (
    <div className={styles.outputSection}>
      {reasoning && (
        <div className={styles.outputItem}>
          <div className={styles.outputLabel}>{t('taskGraph.nodeReasoning')}</div>
          <div className={styles.outputContent}>{reasoning}</div>
        </div>
      )}
      {summary && (
        <div className={styles.outputItem}>
          <div className={styles.outputLabel}>{t('taskGraph.nodeSummary')}</div>
          <div className={styles.outputContent}>{summary}</div>
        </div>
      )}
      {error && (
        <div className={styles.errorSection}>
          <div className={styles.errorLabel}>{t('taskGraph.nodeError')}</div>
          <div className={styles.errorContent}>{error}</div>
        </div>
      )}
    </div>
  );
}
