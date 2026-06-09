import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { TraceItem } from './types';
import ThinkingBlock from './ThinkingBlock';
import TextBlock from './TextBlock';

interface PlanItem {
  name?: string;
  description?: string;
  node_id?: string;
}

interface TraceRendererProps {
  /** 追踪数据对象 */
  trace: TraceItem;
}

/**
 * PlanBlock 组件
 * 渲染子任务计划列表，以简洁的节点列表形式展示
 */
function PlanBlock({ data }: { data: string }) {
  const { t } = useTranslation();

  const items = useMemo<PlanItem[]>(() => {
    try {
      const parsed = JSON.parse(data);
      if (Array.isArray(parsed)) return parsed;
      // 如果是对象且有 nodes 字段（兼容不同格式）
      if (parsed && Array.isArray(parsed.nodes)) return parsed.nodes;
      return [];
    } catch {
      return [];
    }
  }, [data]);

  // JSON 解析失败或为空数组时降级到 TextBlock
  if (items.length === 0) {
    return <TextBlock content={data} />;
  }

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>{t('taskGraph.subTaskPlan')}</div>
      <ol style={{ margin: 0, paddingLeft: 20 }}>
        {items.map((item, index) => (
          <li key={item.node_id || index} style={{ marginBottom: 4 }}>
            {item.name || item.description || `Task ${index + 1}`}
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * TraceRenderer 组件
 * 根据 trace 类型分发渲染对应的子组件。
 * 兼容两种 trace 格式：
 * - 前端格式：{ type: 'thinking'|'text'|'plan', data: string }
 * - 后端 Msg 序列化：{ role: string, content: string, name: string }
 *
 * 注意：key prop 由父组件在列表渲染时指定
 */
export default function TraceRenderer({ trace }: TraceRendererProps) {
  if (!trace) return null;

  // 前端标准格式
  if (trace.type && trace.data) {
    if (trace.type === 'thinking') {
      return <ThinkingBlock content={trace.data} />;
    }
    if (trace.type === 'plan') {
      return <PlanBlock data={trace.data} />;
    }
    return <TextBlock content={trace.data} />;
  }

  // 后端 Msg 序列化格式（role + content）
  if (trace.content !== undefined && trace.content !== null) {
    const content = String(trace.content);
    if (content.trim()) {
      return <TextBlock content={content} />;
    }
  }

  return null;
}
