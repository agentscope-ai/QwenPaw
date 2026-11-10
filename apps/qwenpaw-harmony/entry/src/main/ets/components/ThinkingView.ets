/*
 * 思考视图（thinking view）解析层 —— 会话模型面板的「思考强度」区共用。
 * 两处分派入口：
 *   - GET /api/chats/{id}/thinking            → 当前会话生效的思考视图（宿主：SessionRuntimeBar）
 *   - GET /api/chats/thinking-default?...     → 未选模型时的预览视图（宿主：OptionDialog 实时跟随）
 * 解析口径对齐 console sessionModel 的 thinking_view：
 *   - control 缺失或非对象 → 返回 null（宿主视为无思考控制，整段隐藏）
 *   - kind 仅 effort / budget 两档，其余按 unknown 只读处理
 *   - saved/effective 取值必须带 level 字符串，否则视为缺失
 *   - budget_tokens 取值链：显示档 > budget_default > 区间下限
 *   - effort 档位去重，supports_off 时 'off' 前置
 */

// 思考偏好（saved / effective 的值形态）：level 必填，budget_tokens 可选
export interface ThinkingPref {
  level: string;
  budgetTokens: number;
}

// 解析后的思考视图快照：OptionDialog 与 SessionRuntimeBar 各取所需字段
export interface ThinkingSnapshot {
  kind: string;
  stops: string[];
  supportsOff: boolean;
  budgetMin: number;
  budgetMax: number;
  level: string;
  budgetTokens: number;
  canReset: boolean;
}

// 取 thinking 偏好：level 非字符串视为缺失
export function thinkingPrefOf(v: Object): ThinkingPref | null {
  if (v === undefined || v === null || typeof v !== 'object') {
    return null;
  }
  const r: Record<string, Object> = v as Record<string, Object>;
  const level: Object = r['level'];
  if (typeof level !== 'string' || (level as string).length === 0) {
    return null;
  }
  const out: ThinkingPref = { level: level as string, budgetTokens: 0 };
  const t: Object = r['budget_tokens'];
  if (typeof t === 'number') {
    out.budgetTokens = t as number;
  }
  return out;
}

// 字符串数组防御性提取（服务端 efforts 列表）
function stringArrayOf(v: Object): string[] {
  if (!Array.isArray(v)) {
    return [];
  }
  const out: string[] = [];
  for (const item of v as Object[]) {
    if (typeof item === 'string') {
      out.push(item as string);
    }
  }
  return out;
}

// 解析 thinking view；control 缺失/非对象 → null
export function parseThinkingView(view: Record<string, Object> | null): ThinkingSnapshot | null {
  if (view === null) {
    return null;
  }
  const controlRaw: Object = view['control'];
  if (controlRaw === undefined || controlRaw === null || typeof controlRaw !== 'object') {
    return null;
  }
  const control: Record<string, Object> = controlRaw as Record<string, Object>;

  const kind: string = typeof control['kind'] === 'string' ? control['kind'] as string : 'unknown';
  const supportsOff: boolean = control['supports_off'] === true;
  const efforts: string[] = stringArrayOf(control['efforts']);

  let bMin: number = typeof control['budget_min'] === 'number' ? control['budget_min'] as number : 0;
  let bMax: number = typeof control['budget_max'] === 'number' ? control['budget_max'] as number : 0;
  if (bMin <= 0) {
    bMin = 1;
  }
  if (bMax < bMin) {
    bMax = bMin;
  }

  const saved: ThinkingPref | null = thinkingPrefOf(view['value']);
  const effective: ThinkingPref | null = thinkingPrefOf(view['effective']);
  const savedLevel: string = saved !== null ? saved.level : '';
  // 显示档：显式继承时展示服务端生效值，否则展示已保存值（可能为 null → 未设）
  const displayed: ThinkingPref | null =
    savedLevel === 'inherit' ? (effective !== null ? effective : saved) : saved;
  const dispLevel: string = displayed !== null ? displayed.level : '';
  // token 取值链：显示档 budget_tokens > control.budget_default > 区间下限
  const budgetDefault: Object = control['budget_default'];
  const tokens: number =
    displayed !== null && displayed.budgetTokens > 0 ? displayed.budgetTokens
      : typeof budgetDefault === 'number' && (budgetDefault as number) > 0
        ? budgetDefault as number : bMin;

  // effort 档位：supports_off 时 'off' 前置，efforts 去重（'off' 不重复）
  const stops: string[] = [];
  if (kind === 'effort') {
    if (supportsOff) {
      stops.push('off');
    }
    for (const e of efforts) {
      if (stops.indexOf(e) < 0) {
        stops.push(e);
      }
    }
  }

  const snap: ThinkingSnapshot = {
    kind: kind,
    stops: stops,
    supportsOff: supportsOff,
    budgetMin: bMin,
    budgetMax: bMax,
    level: dispLevel === 'inherit' ? '' : dispLevel,
    budgetTokens: tokens,
    canReset: savedLevel !== 'inherit' || view['model_source'] === 'session'
  };
  return snap;
}
