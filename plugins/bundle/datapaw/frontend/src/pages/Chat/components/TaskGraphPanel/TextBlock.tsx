import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import styles from './TaskNodeDrawer.module.less';

interface TextBlockProps {
  /** Markdown 文本内容 */
  content: string;
}

/**
 * TextBlock 组件
 * 使用 ReactMarkdown 渲染 Markdown 格式的追踪文本内容
 * 支持 GFM（GitHub Flavored Markdown）扩展语法
 */
export default function TextBlock({ content }: TextBlockProps) {
  return (
    <div className={`${styles.textBlock} ${styles.markdownBody}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
