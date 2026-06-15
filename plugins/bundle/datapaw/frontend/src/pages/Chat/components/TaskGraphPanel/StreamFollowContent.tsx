import { useTranslation } from 'react-i18next';
import { ToolCall } from '@agentscope-ai/chat';
import type { StreamEvent } from './types';
import LoadingDots from './LoadingDots';
import TextBlock from './TextBlock';
import ThinkingBlock from './ThinkingBlock';
import FetchDataBlock from '../FetchDataBlock';
import styles from './TaskNodeDrawer.module.less';

export interface StreamFollowContentProps {
  agentType?: string;
  streamEvents: StreamEvent[];
  showStreamingIndicator?: boolean;
}

export default function StreamFollowContent({
  agentType,
  streamEvents,
  showStreamingIndicator = false,
}: StreamFollowContentProps) {
  const { t } = useTranslation();

  return (
    <>
      {agentType && (
        <div className={styles.agentTitle}>
          <span className={styles.agentBadge}>{agentType}</span>
        </div>
      )}

      {streamEvents.map((event, idx) => {
        if (event.type === 'text') {
          return <TextBlock key={`text-${idx}`} content={event.text} />;
        }
        if (event.type === 'tool_call') {
          if (event.name === 'fetch_data') {
            return (
              <FetchDataBlock
                key={event.call_id || `tool-${idx}`}
                argumentsStr={event.arguments}
                output={event.output}
                loading={!event.output}
                fallbackTitle={event.name}
              />
            );
          }

          let inputContent = event.arguments || '{}';
          if (typeof inputContent === 'object') {
            inputContent = JSON.stringify(inputContent, null, 2);
          }
          let outputContent = event.output || '';
          if (outputContent && typeof outputContent === 'string') {
            try {
              outputContent = JSON.stringify(JSON.parse(outputContent), null, 2);
            } catch {
              // keep raw string
            }
          }
          return (
            <ToolCall
              key={event.call_id || `tool-${idx}`}
              title={event.name}
              input={inputContent}
              output={outputContent}
              defaultOpen={false}
            />
          );
        }
        if (event.type === 'thinking') {
          return <ThinkingBlock key={`thinking-${idx}`} content={event.thinking} />;
        }
        return null;
      })}

      {streamEvents.length === 0 && !showStreamingIndicator && (
        <div className={styles.emptyState}>{t('taskGraph.noTrace')}</div>
      )}

      {showStreamingIndicator && <LoadingDots />}
    </>
  );
}
