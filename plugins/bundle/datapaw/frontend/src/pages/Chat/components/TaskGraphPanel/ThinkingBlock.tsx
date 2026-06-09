import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import styles from './TaskNodeDrawer.module.less';

interface ThinkingBlockProps {
  /** 思考内容文本 */
  content: string;
}

/**
 * ThinkingBlock 组件
 * 渲染可折叠的思考过程块，默认展开状态
 * 点击标题栏可切换展开/收起
 */
export default function ThinkingBlock({ content }: ThinkingBlockProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);

  // 抽屉中：thinking 块末尾补一行空行——确保 split('\n') 后末尾总有一个空字符串元素，
  // 渲染为空 <p>，形成近似一行高度的空白（依赖 line-height: 1.7）。
  const lines = content.split('\n');
  if (lines[lines.length - 1] !== '') lines.push('');

  return (
    <details className={styles.thinkingBlock} open={open}>
      <summary
        className={styles.thinkingSummary}
        onClick={(e) => {
          e.preventDefault();
          setOpen(!open);
        }}
      >
        <span className={`${styles.thinkingChevron} ${open ? styles.thinkingChevronOpen : ''}`}>
          ▶
        </span>
        <span className={styles.thinkingIcon}>🧠</span>
        <span className={styles.thinkingLabel}>{t('taskGraph.thinkingProcess')}</span>
        <span className={styles.thinkingHint}>
          {open ? t('taskGraph.clickToCollapse') : t('taskGraph.clickToExpand')}
        </span>
      </summary>
      <div className={styles.thinkingContent}>
        {lines.map((line, i) => (
          <p key={i} className={styles.thinkingLine}>
            {line}
          </p>
        ))}
      </div>
    </details>
  );
}
