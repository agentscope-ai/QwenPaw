import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import LoadingDots from '../TaskGraphPanel/LoadingDots';
import styles from './index.module.less';

/**
 * 从 fetch_data 工具的 input arguments 中提取用作标题的文本。
 * 优先 query，其次 text / question / prompt，再其次首个字符串值，最后降级为原始字符串。
 */
export function extractFetchDataTitle(argumentsStr: string | undefined | null): string {
  if (!argumentsStr) return '';
  const trimmed = String(argumentsStr).trim();
  if (!trimmed || trimmed === '{}') return '';
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const preferKeys = ['query', 'text', 'question', 'prompt'];
      for (const k of preferKeys) {
        const v = (parsed as Record<string, unknown>)[k];
        if (typeof v === 'string' && v.trim()) return v;
      }
      for (const v of Object.values(parsed as Record<string, unknown>)) {
        if (typeof v === 'string' && v.trim()) return v;
      }
    }
    if (typeof parsed === 'string') return parsed;
  } catch {
    // 解析失败降级为原始字符串
  }
  return trimmed;
}

export interface FetchDataParsedOutput {
  columns?: string[];
  data?: unknown[][];
  sql?: string;
  shape?: [number, number];
  cache_hit?: boolean;
  file_path?: string;
}

/**
 * 解析 fetch_data 的 output 字段。
 * Output 格式：JSON 字符串 [{ type: 'text', text: '<inner JSON>' }]
 * Inner JSON：{ columns, data, shape, sql, cache_hit, file_path }
 */
export function parseFetchDataOutput(
  outputStr: string | undefined | null,
): FetchDataParsedOutput | null {
  if (!outputStr) return null;
  const raw = String(outputStr).trim();
  if (!raw) return null;
  try {
    let payload: unknown = JSON.parse(raw);
    // 数组包装: [{type:'text', text:'<json>'}] → 提取首个元素的 text
    if (Array.isArray(payload) && payload.length > 0) {
      const first = payload[0] as Record<string, unknown>;
      if (first && typeof first === 'object' && typeof first.text === 'string') {
        try {
          payload = JSON.parse(first.text);
        } catch {
          return null;
        }
      }
    }
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
      const p = payload as Record<string, unknown>;
      return {
        columns: Array.isArray(p.columns) ? (p.columns as string[]) : undefined,
        data: Array.isArray(p.data) ? (p.data as unknown[][]) : undefined,
        sql: typeof p.sql === 'string' ? p.sql : undefined,
        shape: Array.isArray(p.shape) ? (p.shape as [number, number]) : undefined,
        cache_hit: typeof p.cache_hit === 'boolean' ? p.cache_hit : undefined,
        file_path: typeof p.file_path === 'string' ? p.file_path : undefined,
      };
    }
  } catch {
    return null;
  }
  return null;
}

export interface FetchDataBlockProps {
  /** input arguments（JSON 字符串），用于解析标题 */
  argumentsStr?: string | null;
  /** output（JSON 字符串），用于解析 columns / data / sql */
  output?: string | null;
  /** 是否正在加载（外层可传入；output 为空时默认视为 loading） */
  loading?: boolean;
  /** 当 arguments 解析不出标题时的兜底文案，通常是工具名 */
  fallbackTitle?: string;
}

/**
 * FetchDataBlock 通用组件
 * 将 fetch_data 工具调用以"📊 标题 + SQL (Markdown) + 结果表格"的形式展示。
 * 同时适用于任务节点抽屉、主 Chat 消息气泡等场景。
 */
export default function FetchDataBlock({
  argumentsStr,
  output,
  loading,
  fallbackTitle,
}: FetchDataBlockProps) {
  const { t } = useTranslation();
  const title = extractFetchDataTitle(argumentsStr);
  const parsed = parseFetchDataOutput(output);
  const hasTable = !!(parsed && parsed.columns && parsed.data);
  const rowCount = parsed?.shape?.[0] ?? parsed?.data?.length ?? 0;
  const isLoading = loading || !output;

  return (
    <div className={styles.fetchDataBlock}>
      <div className={styles.fetchDataTitle}>
        <span>📊 {title || fallbackTitle || 'fetch_data'}</span>
      </div>

      {hasTable && (
        <div className={styles.fetchDataSection}>
          <div className={styles.fetchDataSectionTitle}>
            {t('taskGraph.fetchDataResult')}
            {rowCount > 0
              ? ` (${t('taskGraph.fetchDataRows', { count: rowCount })})`
              : ''}
          </div>
          <div className={styles.dataTableWrapper}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  {parsed!.columns!.map((col, ci) => (
                    <th key={ci}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {parsed!.data!.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {(Array.isArray(row) ? row : [row]).map((cell, cIdx) => (
                      <td key={cIdx}>
                        {typeof cell === 'object' && cell !== null
                          ? JSON.stringify(cell)
                          : String(cell ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {parsed?.sql && (
        <div className={styles.fetchDataSection}>
          <div className={styles.fetchDataSectionTitle}>SQL</div>
          <div className={styles.markdownBody}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {`\`\`\`sql\n${parsed.sql.trim()}\n\`\`\``}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {!parsed && output && (
        <div className={styles.fetchDataSection}>
          <div className={styles.fetchDataSectionTitle}>Output</div>
          <pre className={styles.fetchDataPre}>{output}</pre>
        </div>
      )}

      {isLoading && !parsed && (
        <div className={styles.fetchDataSection}>
          <div className={styles.loadingWrap}>
            <LoadingDots />
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 主 Chat 侧的适配器：用于 AgentScopeRuntimeWebUI 的 `customToolRenderConfig`。
 *
 * 库内 Tool.js 的调用方式：<C data={data} />
 *   - data.content[0].data.arguments → input arguments
 *   - data.content[1].data.output    → output
 *   - data.status === 'IN_PROGRESS'  → loading
 *
 * 用法示例：
 *   options.customToolRenderConfig = { fetch_data: FetchDataToolAdapter };
 */
interface ToolRenderData {
  status?: string;
  content?: Array<{
    type?: string;
    data?: {
      name?: string;
      arguments?: string | Record<string, unknown>;
      output?: string | unknown;
      [k: string]: unknown;
    };
  }>;
}

export function FetchDataToolAdapter({ data }: { data: ToolRenderData }) {
  const content = data?.content ?? [];
  const rawArgs = content[0]?.data?.arguments;
  const rawOutput = content[1]?.data?.output;
  const argumentsStr =
    typeof rawArgs === 'string' ? rawArgs : rawArgs ? JSON.stringify(rawArgs) : '';
  const outputStr =
    typeof rawOutput === 'string'
      ? rawOutput
      : rawOutput !== undefined && rawOutput !== null
        ? JSON.stringify(rawOutput)
        : '';
  const loading = data?.status === 'IN_PROGRESS';
  const fallbackTitle = content[0]?.data?.name || 'fetch_data';

  return (
    <FetchDataBlock
      argumentsStr={argumentsStr}
      output={outputStr}
      loading={loading}
      fallbackTitle={fallbackTitle}
    />
  );
}
