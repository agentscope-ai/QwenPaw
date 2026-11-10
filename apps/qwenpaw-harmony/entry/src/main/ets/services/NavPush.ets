/*
 * 路由入栈的统一入口（同一目标去重）。
 *
 * 为什么不用平台自带的单例模式：SDK（ets/component/navigation.d.ts，since 12）的
 * pushPath(info, { launchMode }) 有 MOVE_TO_TOP_SINGLETON / POP_TO_SINGLETON 两种单例语义，
 * 但两者的判重键都只是 **路由名**（"栈中已存在同名 NavDestination 则移到栈顶 / 弹到该页"）。
 * 本工程所有会话共用同一个注册路由名（router_map 的 'chat'），按名判重会把 A 会话当成 B 会话的
 * 同一页 —— 点开另一个会话反而回到已打开的那个。故这里按「路由名 + 入栈参数」判重：
 *   · 同目标已在栈顶     → 忽略本次入栈（连点同一项不再叠出多份页面）；
 *   · 同目标在栈中更深处 → 弹回该页（等价平台单例语义，但多带了会话 id / 模块 key 这一维）；
 *   · 栈中没有该目标     → 正常入栈。
 * 判重位置与官方口径一致：FAQ《从系统卡片跳转app页面，重复多次进入导致需要多次才能返回》
 * (faqs-arkui-858) 给出的修改建议即"入栈前判断目标是否已在栈顶，在则不再 push 新的页面"。
 *
 * 判重键 = 路由名 + 参数中基本类型字段（见 routeKeyOf）。参数里常带 NavPathStack 这类运行时对象，
 * 它们不做键的一部分；键整体取不到时退化为只按路由名判重——对登录 / 部署这类"同页只应存在一份"
 * 的页面，按名判重仍是正确行为。
 */

/** 路由入栈（带同目标去重）。param 省略时按路由名判重。 */
export function pushRoute(stack: NavPathStack, name: string, param?: Object): void {
  const names: string[] = stack.getAllPathName();
  const key: string = routeKeyOf(name, param);
  for (let i = names.length - 1; i >= 0; i--) {
    if (names[i] !== name || routeKeyOf(names[i], paramAt(stack, i)) !== key) {
      continue;
    }
    if (i === names.length - 1) {
      return;
    }
    stack.popToIndex(i);
    return;
  }
  stack.pushPath({ name: name, param: param });
}

/*
 * 单实例路由入栈（同名页在栈中只保留一份）——会话 / 内容详情页共用。
 * 分栏下"点开另一个目标"应当是**换窗口**：右栏换成新目标、返回直接回到空态，
 * 而不是把新目标叠在旧目标之上（那样返回会先回到上一个目标，窗口也会越堆越多）。故：
 *   · 栈顶已是同一目标 → 不动（连点同一项不重建）；
 *   · 同名页在栈中、但目标不同 → 新目标入栈（新页在上、自右覆盖进来），**转场结束后**再删同名旧页；
 *   · 栈中没有同名页 → 正常入栈。
 *
 * 为什么不能只用 replacePath：它只替换栈顶页面的**路由信息**，同名页的 NavDestination 实例会被复用，
 * 页面取不到新参数（官方 NavDestination 文档明示 "replacePath、replaceDestination 不会触发 onNewParam"，
 * 实例复用又不会再走 aboutToAppear）——真机实测即"点另一条内容，右栏不变"。
 * 官方 FAQ《分栏模式下，页面切换无响应》(faqs-arkui-538) 症状同源：同名页未重建则内容不更新。
 *
 * 为什么删旧页要等转场结束（真机抓帧取证）：删除会让旧页播一遍"退出"（向右滑走）——它此时压在
 * 新页之上，观感就是"旧的往右跑、新的像在底下被加载"（判为方向反了）。改成"新页先整个盖上去、
 * 补间走完再把旧页删掉"，看到的才是"新页覆盖旧页、旧页随后销毁"。
 */
export function swapRoute(stack: NavPathStack, name: string, param?: Object): void {
  const names: string[] = stack.getAllPathName();
  const top: number = names.length - 1;
  if (top >= 0 && names[top] === name
    && routeKeyOf(name, paramAt(stack, top)) === routeKeyOf(name, param)) {
    return;
  }
  stack.pushPath({ name: name, param: param });
  setTimeout((): void => {
    dropSameNameBelowTop(stack, name);
  }, SLIDE_COVER_MS + 80);
}

// 删掉栈中"同名但不是栈顶"的页（栈顶是本轮刚入栈的新页，绝不能动）。
// 从下往上逐个删：删靠后的索引不会影响前面索引的对应关系。
function dropSameNameBelowTop(stack: NavPathStack, name: string): void {
  const names: string[] = stack.getAllPathName();
  const top: number = names.length - 1;
  for (let i = top - 1; i >= 0; i--) {
    if (names[i] === name) {
      stack.removeByIndexes([i]);
    }
  }
}

/*
 * 二级页转场：整页自右水平覆盖进来，退出时滑回右侧（push/pop 同向）。
 *
 * 为什么不用 systemTransition 的默认档：分栏下那套动的是"内容区左边缘 0 → 分栏位"，观感是从
 * 左侧摊过来（真机判"方向反了"；同一表单栏下（手机竖屏）方向是对的）。官方口径里系统转场不满意时
 * 应改用 customTransition（NavDestinationTransitionDelegate：delegate 里先把页面摆到入场位，
 * 再在 transition.event 内改状态，由框架按 duration/curve 补间）。
 * x 用百分比：入场 100% = 页面先停在右侧屏外 → 补间到 0（自右向左覆盖）；出场反向滑回右侧。
 * 每个二级页各自持有 @State pageX（页面私有状态），本函数只负责"何时摆到哪"，便于共用同一套方向。
 */
export function slideCoverTransition(op: NavigationOperation, isEnter: boolean,
  setX: (v: string) => void): Array<NavDestinationTransition> | undefined {
  const offscreen: string = '100%';
  const home: string = '0%';
  let from: string = home;
  let to: string = home;
  if (op === NavigationOperation.PUSH) {
    if (isEnter) {
      from = offscreen;
    }
  } else if (op === NavigationOperation.POP) {
    if (!isEnter) {
      to = offscreen;
    }
  }
  setX(from);
  const step: NavDestinationTransition = {
    duration: SLIDE_COVER_MS,
    delay: 0,
    curve: Curve.Friction,
    event: (): void => {
      setX(to);
    }
  };
  return [step];
}

// 二级页水平覆盖转场时长（ms）：与系统 push 同档（略快于 pop 的观感更利落）
const SLIDE_COVER_MS: number = 320;

/*
 * NavDestination 自己的返回处理：把本页出栈并消费返回事件（返回 true）。
 * 为什么每个二级页都要挂：HDS 标题栏左上角的返回按钮与系统侧滑都只投递到**当前 NavDestination 的
 * onBackPressed 回调**（官方 FAQ faqs-arkui-1117：该回调"支持拦截系统侧滑及 NavDestination 标题栏的
 * 返回事件"）。页面没挂它时，标题栏返回按钮点了没有反应（真机实测：工作台/社区二级页），
 * 而根页的 onBackPress 只兜住系统返回键 —— 两条入口都要各归其位。
 */
export function popSelfOnBack(stack: NavPathStack | null): boolean {
  if (stack !== null && stack.size() > 0) {
    stack.pop();
  }
  return true;
}

/*
 * 栈顶是否就是该路由。用于带 onPop 回调的 pushPathByName：回调不能丢，故只在"栈顶已是目标"时
 * 跳过本次入栈，其余情况仍走原接口（带 New 参数入栈、返回时回调）。
 */
export function topRouteIs(stack: NavPathStack, name: string): boolean {
  const names: string[] = stack.getAllPathName();
  return names.length > 0 && names[names.length - 1] === name;
}

function paramAt(stack: NavPathStack, index: number): Object | undefined {
  try {
    const raw: Object | undefined = stack.getParamByIndex(index) as Object | undefined;
    return raw;
  } catch (e) {
    return undefined;
  }
}

/*
 * 判重键 = 路由名 + 参数中**基本类型字段**的排序拼接。
 * 只用基本类型：入栈参数里常带 NavPathStack 这类运行时对象（页面拿它继续导航），它们不可序列化、
 * 每次也都是新引用；若把整个参数 JSON 化，键会在同一路由名下退化成相同值 —— 于是"点另一条内容"
 * 被判成"重复打开同一项"而不再入栈（分栏下即右栏不换内容）。基本类型字段恰好就是业务身份
 * （会话 id / 内容 id / 模块 key），用它做键才能把"同一目标"和"同路由名的不同目标"分开。
 */
function routeKeyOf(name: string, param: Object | undefined): string {
  if (param === undefined) {
    return name;
  }
  if (typeof param === 'string') {
    return `${name}|${param as string}`;
  }
  const parts: string[] = [];
  try {
    const rec: Record<string, Object> = param as Record<string, Object>;
    const keys: string[] = Object.keys(rec);
    for (let i = 0; i < keys.length; i++) {
      const v: Object = rec[keys[i]];
      if (typeof v === 'string') {
        parts.push(`${keys[i]}=${v as string}`);
      } else if (typeof v === 'number') {
        parts.push(`${keys[i]}=${(v as number).toString()}`);
      } else if (typeof v === 'boolean') {
        parts.push(`${keys[i]}=${(v as boolean).toString()}`);
      }
    }
  } catch (e) {
    return name;
  }
  parts.sort();
  return `${name}|${parts.join('&')}`;
}
