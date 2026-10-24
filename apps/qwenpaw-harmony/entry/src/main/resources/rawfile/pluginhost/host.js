/*
 * QwenPaw 本地插件宿主 shell（无服务端离线运行）。
 *
 * 与 console 宿主（console/src/plugins/hostExternals.ts + hostSdk/install.ts）同一契约：
 * 插件 bundle 通过 window.QwenPaw.* 声明式注册（host / menu / route / slot / chat /
 * audit / memoryBackends / registerRoutes），本 shell 在 ArkWeb 内以本地 UMD 运行时
 * （vendor/ 目录的 React 18 + antd 5 + dayjs）承载渲染。
 *
 * 宿主形态与数据面（两轴模型，契约 apiVersion 1.0）：
 *   - 轴 A 宿主形态（host.env.kind）：本 shell 声明 'local'——端侧独立宿主，无
 *     QwenPaw 服务端，插件后端（Python 端点）不存在。命名纪律：「独立/local」只
 *     指宿主形态，「离线/offline」只指连通性——旧 isOffline 单布尔已废弃（二者
 *     正交：独立宿主下数据面可以可达，服务端宿主下也可以不可达）。
 *   - 轴 B 能力位（host.env.caps）：{ net, secureStore, notify }——端侧桥
 *     （qpwNet 网络 / qpwSecure 凭据）落地后置 true；notify 恒 true（Notification
 *     桩已接系统通知中心）。插件按能力位决定数据面与凭据策略，不得以单一布尔
 *     推断宿主形态。
 *   - 数据面现状（受控失败，不静默）：host.fetch 与页面裸 fetch 都被接管——
 *     http(s):// 与根相对 '/api/...' 视为服务端请求 → 受控 503（JSON detail 说明
 *     数据面不可达）；host.getApiUrl 把 /api/frontend_plugin/{本应用}/files/*
 *     映射为本地相对路径（插件自带静态资源直接读沙箱文件，等价服务端 files
 *     端点）；其余相对静态资源放行。qpwNet 桥落地后此处改走桥转发，契约形状
 *     不变。
 *   - chat.* 命名空间完整可注册（LIFO 栈与 console 一致），但本 shell 无聊天面，
 *     注册仅存储不呈现（no-op 表面）。
 *
 * 三形态（手机 / 平板 / PC）：matchMedia 断点 —— <768px 抽屉式菜单；768~1199px 可折叠
 * 侧栏；≥1200px 常驻宽侧栏。单路由应用（典型 PawApp）直接整页渲染，不出菜单壳。
 * PawApp（manifest meta.pawapp，原生侧传 qpw_pawapp=1）强制整页：插件多路由注册
 * （PawApp /apps/ + 侧栏 /plugin/）也不出左侧菜单壳（Sider / drawer / ☰）——本地
 * 宿主是单页容器，入口页取 meta.pawapp.entry_page（qpw_pawapp_route）。
 */
(function () {
  'use strict';

  // ── URL 参数（原生页传入） ──────────────────────────────────────────────
  var params = new URLSearchParams(window.location.search);
  var APP_ID = params.get('paw_app') || '';
  var ENTRY = params.get('qpw_entry') || '';
  var LOCALE = params.get('qpw_locale') || (navigator.language || 'zh-CN');
  var OFFLINE_DETAIL = '数据面不可达（独立宿主：未连接 QwenPaw 服务端，端侧网络桥未就绪）';
  // PawApp（manifest meta.pawapp）单页标记 + 入口路由（原生侧读 plugin.json 后传入）：
  // 单页模式下壳不渲染左侧菜单壳（见文件头「三形态」注）
  var PAWAPP = params.get('qpw_pawapp') === '1';
  var PAWAPP_ROUTE = params.get('qpw_pawapp_route') || '';

  // ── 本地文件映射：服务端 files 端点 → 沙箱内插件目录相对路径 ────────────
  function localFileRel(path) {
    var p = (typeof path === 'string' && path.charAt(0) === '/') ? path : '/' + path;
    var filesPrefix = '/api/frontend_plugin/' + APP_ID + '/files/';
    if (p.indexOf(filesPrefix) === 0) {
      return 'plugins/' + APP_ID + '/' + p.substring(filesPrefix.length);
    }
    return null;
  }

  // ── 受控离线 fetch：服务端请求 → 503 JSON；本地相对资源放行 ─────────────
  var origFetch = window.fetch ? window.fetch.bind(window) : null;
  function offlineResponse() {
    try {
      return new Response(JSON.stringify({ detail: OFFLINE_DETAIL, code: 'OFFLINE' }), {
        status: 503,
        statusText: 'Service Unavailable (offline)',
        headers: { 'Content-Type': 'application/json' }
      });
    } catch (e) {
      var err = new Error(OFFLINE_DETAIL);
      err.offline = true;
      return Promise.reject(err);
    }
  }
  function isServerUrl(raw) {
    if (!raw || typeof raw !== 'string') return false;
    if (/^https?:/i.test(raw)) return true;
    return raw.charAt(0) === '/' && raw.charAt(1) !== '/';
  }
  window.fetch = function (input, init) {
    var raw = (typeof input === 'string') ? input : (input && input.url) || '';
    var mapped = localFileRel(raw);
    if (mapped !== null) {
      return origFetch ? origFetch(mapped, init) : offlineResponse();
    }
    if (isServerUrl(raw)) {
      return offlineResponse();
    }
    if (!origFetch) {
      return Promise.reject(new Error('fetch 不可用'));
    }
    return origFetch(input, init);
  };

  // ── Notification 桩：构造调用转 prompt 桥，由原生侧 onPrompt 接住转发系统通知 ──
  (function () {
    function QPN(t, o) {
      var b = (o && o.body) ? String(o.body) : '';
      // 语义化载荷（契约 v1）：kind（approval/task/alert）+ target（插件内深链 id）
      // 仅在插件提供时透传——旧插件只发 {t,b}，行为不变。
      var payload = { t: String(t), b: b };
      if (o) {
        if (o.kind) payload.kind = String(o.kind);
        if (o.target) payload.target = String(o.target);
      }
      try {
        console.error('[pluginhost] Notification 桩触发，prompt 转发通知中心: ' + b);
        window.prompt('qwpaw.notify|' + JSON.stringify(payload), '');
        console.error('[pluginhost] prompt 已返回（原生侧已接管）');
      } catch (e) {
        console.error('[pluginhost] Notification 桩 prompt 抛错: ' + (e && e.message ? e.message : String(e)));
      }
    }
    QPN.permission = 'granted';
    QPN.requestPermission = function () { return Promise.resolve('granted'); };
    QPN.prototype.close = function () {};
    window.Notification = QPN;
  })();

  // ── 注册表（route / menu / slot / chat / audit；与 console 同名同语义子集） ──
  var routes = []; // { id, path, component, label, icon, priority, pluginId, wrapper }
  var menus = []; // { id, pluginId, item }
  var slots = {}; // name -> [{ id, pluginId, render }]
  var auditLog = [];
  var version = 0;
  var listeners = [];
  function notify() {
    version += 1;
    for (var i = 0; i < listeners.length; i++) listeners[i]();
  }
  function subscribe(fn) {
    listeners.push(fn);
    return function () {
      listeners.splice(listeners.indexOf(fn), 1);
    };
  }
  function getVersion() {
    return version;
  }
  function makeDispose(fn) {
    return { dispose: fn || function () {} };
  }

  function removeRoute(id) {
    for (var i = routes.length - 1; i >= 0; i--) {
      if (routes[i].id === id) routes.splice(i, 1);
    }
  }
  function addRoute(pluginId, spec) {
    var r = {
      id: spec.id || (pluginId + ':' + spec.path),
      path: spec.path,
      component: spec.component,
      label: spec.label || spec.path,
      icon: spec.icon || '',
      priority: typeof spec.priority === 'number' ? spec.priority : 0,
      pluginId: pluginId,
      wrapper: null
    };
    removeRoute(r.id);
    routes.push(r);
    notify();
    return makeDispose(function () { removeRoute(r.id); notify(); });
  }

  // chat 离线存储表面：字段各自 LIFO 栈（与 console chatExtensions.setScalar 一致）
  var chatScalars = {};
  var chatLists = {
    rightHeader: [], senderPrefix: [], suggestions: [], actions: [], requestActions: [],
    requestPayload: [], requestPrepend: [], requestAppend: [],
    responsePrepend: [], responseAppend: [], toolRender: [], approval: [], cards: []
  };
  var chatRender = { request: null, response: null };
  function chatSetScalar(pluginId, field, value) {
    var stack = chatScalars[field] || (chatScalars[field] = []);
    stack.push({ pluginId: pluginId, value: value });
    return makeDispose(function () {
      var s = chatScalars[field];
      for (var i = s.length - 1; i >= 0; i--) {
        if (s[i].pluginId === pluginId) { s.splice(i, 1); break; }
      }
    });
  }
  function chatAddList(listKey, pluginId, item) {
    chatLists[listKey].push({ pluginId: pluginId, item: item });
    return makeDispose(function () {
      var l = chatLists[listKey];
      for (var i = l.length - 1; i >= 0; i--) {
        if (l[i].pluginId === pluginId && l[i].item === item) { l.splice(i, 1); break; }
      }
    });
  }
  var chatNamespace = {
    welcome: {
      set: function (pid, partial) {
        var ds = [];
        for (var k in partial) {
          if (Object.prototype.hasOwnProperty.call(partial, k)) ds.push(chatSetScalar(pid, 'welcome.' + k, partial[k]));
        }
        return makeDispose(function () { for (var i = 0; i < ds.length; i++) ds[i].dispose(); });
      },
      render: function (pid, value) { return chatSetScalar(pid, 'welcome.render', value); }
    },
    theme: {
      set: function (pid, partial) {
        var ds = [];
        for (var k in partial) {
          if (Object.prototype.hasOwnProperty.call(partial, k)) ds.push(chatSetScalar(pid, 'theme.' + k, partial[k]));
        }
        return makeDispose(function () { for (var i = 0; i < ds.length; i++) ds[i].dispose(); });
      }
    },
    leftHeader: {
      set: function (pid, partial) {
        var ds = [];
        for (var k in partial) {
          if (Object.prototype.hasOwnProperty.call(partial, k)) ds.push(chatSetScalar(pid, 'header.' + k, partial[k]));
        }
        return makeDispose(function () { for (var i = 0; i < ds.length; i++) ds[i].dispose(); });
      },
      render: function (pid, node) { return chatSetScalar(pid, 'header.leftRender', node); }
    },
    rightHeader: { add: function (pid, node, opts) { return chatAddList('rightHeader', pid, { node: node, id: opts && opts.id, order: opts && opts.order }); } },
    sender: {
      set: function (pid, partial) {
        var ds = [];
        for (var k in partial) {
          if (Object.prototype.hasOwnProperty.call(partial, k)) ds.push(chatSetScalar(pid, 'sender.' + k, partial[k]));
        }
        return makeDispose(function () { for (var i = 0; i < ds.length; i++) ds[i].dispose(); });
      },
      addPrefix: function (pid, node, opts) { return chatAddList('senderPrefix', pid, { node: node, id: opts && opts.id }); },
      addSuggestion: function (pid, item) { return chatAddList('suggestions', pid, item); }
    },
    actions: { add: function (pid, spec) { return chatAddList('actions', pid, spec); } },
    requestActions: { add: function (pid, spec) { return chatAddList('requestActions', pid, spec); } },
    requestPayload: { add: function (pid, fn, opts) { return chatAddList('requestPayload', pid, { transform: fn, id: opts && opts.id }); } },
    request: {
      render: function (pid, fn) { chatRender.request = { pluginId: pid, fn: fn }; return makeDispose(function () { chatRender.request = null; }); },
      prepend: function (pid, fn, opts) { return chatAddList('requestPrepend', pid, { render: fn, id: opts && opts.id }); },
      append: function (pid, fn, opts) { return chatAddList('requestAppend', pid, { render: fn, id: opts && opts.id }); }
    },
    response: {
      set: function (pid, partial) {
        var ds = [];
        for (var k in partial) {
          if (Object.prototype.hasOwnProperty.call(partial, k)) ds.push(chatSetScalar(pid, 'response.' + k, partial[k]));
        }
        return makeDispose(function () { for (var i = 0; i < ds.length; i++) ds[i].dispose(); });
      },
      render: function (pid, fn) { chatRender.response = { pluginId: pid, fn: fn }; return makeDispose(function () { chatRender.response = null; }); },
      prepend: function (pid, fn, opts) { return chatAddList('responsePrepend', pid, { render: fn, id: opts && opts.id }); },
      append: function (pid, fn, opts) { return chatAddList('responseAppend', pid, { render: fn, id: opts && opts.id }); }
    },
    toolRender: function (pid, toolName, render) { return chatAddList('toolRender', pid, { name: toolName, render: render }); },
    approval: { render: function (pid, sourceType, render) { return chatAddList('approval', pid, { sourceType: sourceType, render: render }); } },
    card: function (pid, cardName, render) { return chatAddList('cards', pid, { name: cardName, render: render }); },
    disposeAll: function (pid) {
      for (var f in chatScalars) {
        if (Object.prototype.hasOwnProperty.call(chatScalars, f)) {
          var s = chatScalars[f];
          for (var i = s.length - 1; i >= 0; i--) if (s[i].pluginId === pid) s.splice(i, 1);
        }
      }
      for (var key in chatLists) {
        if (Object.prototype.hasOwnProperty.call(chatLists, key)) {
          var l = chatLists[key];
          for (var j = l.length - 1; j >= 0; j--) if (l[j].pluginId === pid) l.splice(j, 1);
        }
      }
      if (chatRender.request && chatRender.request.pluginId === pid) chatRender.request = null;
      if (chatRender.response && chatRender.response.pluginId === pid) chatRender.response = null;
    }
  };

  // ── window.QwenPaw 命名空间 ─────────────────────────────────────────────
  var QP = window.QwenPaw || (window.QwenPaw = {});
  QP.host = {
    React: window.React,
    ReactDOM: window.ReactDOM,
    antd: window.antd,
    antdIcons: window.icons || {},
    // 两轴契约（v1）：轴 A 宿主形态 + 轴 B 端侧能力位（见文件头说明）。
    // net/secureStore 待端侧 qpwNet/qpwSecure 桥落地后置 true。
    env: {
      kind: 'local',
      caps: { net: false, secureStore: false, notify: true },
      apiVersion: '1.0'
    },
    apiBaseUrl: '',
    getApiUrl: function (path) {
      var p = (typeof path === 'string' && path.charAt(0) === '/') ? path : '/' + path;
      var local = localFileRel(p);
      if (local !== null) return local;
      return '/api' + p;
    },
    getApiToken: function () { return ''; },
    prepareBrowserSession: function (op) { return Promise.resolve().then(op); },
    usesBrowserSession: function () { return false; },
    useTheme: function () { return darkMode ? 'dark' : 'light'; },
    useLocale: function () { return LOCALE; },
    useSelectedAgent: function () { return { id: 'default' }; },
    useCurrentSession: function () { return null; },
    getSelectedAgentId: function () { return 'default'; },
    getCurrentSessionId: function () { return null; },
    fetch: function (path, init) { return window.fetch(QP.host.getApiUrl(path), init); }
  };
  QP.menu = {
    add: function (pluginId, item) {
      var items = Array.isArray(item) ? item : [item];
      var ds = [];
      items.forEach(function (i) {
        menus.push({ id: i.id || (pluginId + ':menu:' + menus.length), pluginId: pluginId, item: i });
        ds.push(makeDispose(function () {
          for (var k = menus.length - 1; k >= 0; k--) if (menus[k] === ds[0]._rec) menus.splice(k, 1);
        }));
      });
      notify();
      return makeDispose(function () {
        menus = menus.filter(function (m) { return m.pluginId !== pluginId; });
        notify();
      });
    },
    replace: function (pluginId, targetId, item) {
      for (var i = 0; i < menus.length; i++) {
        if (menus[i].id === targetId) { menus[i].item = item; menus[i].pluginId = pluginId; notify(); break; }
      }
      return makeDispose(function () {});
    },
    remove: function (targetId) {
      menus = menus.filter(function (m) { return m.id !== targetId; });
      notify();
    },
    snapshot: function () { return menus.map(function (m) { return m.item; }); }
  };
  QP.route = {
    add: function (pluginId, route) {
      var rs = Array.isArray(route) ? route : [route];
      var ds = rs.map(function (r) { return addRoute(pluginId, r); });
      return makeDispose(function () { for (var i = 0; i < ds.length; i++) ds[i].dispose(); });
    },
    replace: function (pluginId, targetId, component) {
      for (var i = 0; i < routes.length; i++) {
        if (routes[i].id === targetId) {
          routes[i].component = component;
          notify();
          return makeDispose(function () { removeRoute(targetId); notify(); });
        }
      }
      return makeDispose(function () {});
    },
    wrap: function (pluginId, targetId, wrapper) {
      for (var i = 0; i < routes.length; i++) {
        if (routes[i].id === targetId) { routes[i].wrapper = wrapper; notify(); break; }
      }
      return makeDispose(function () {
        for (var j = 0; j < routes.length; j++) {
          if (routes[j].id === targetId) { routes[j].wrapper = null; notify(); break; }
        }
      });
    },
    remove: function (targetId) { removeRoute(targetId); notify(); }
  };
  QP.slot = {
    fill: function (pluginId, name, render, opts) {
      (slots[name] || (slots[name] = [])).push({ id: (opts && opts.id) || (pluginId + ':' + name), pluginId: pluginId, render: render });
      notify();
      return makeDispose(function () {
        slots[name] = (slots[name] || []).filter(function (s) { return s.pluginId !== pluginId; });
        notify();
      });
    },
    replace: function (pluginId, name, render, opts) {
      slots[name] = [{ id: (opts && opts.id) || (pluginId + ':' + name), pluginId: pluginId, render: render }];
      notify();
      return makeDispose(function () { delete slots[name]; notify(); });
    },
    snapshot: function () {
      var out = [];
      for (var n in slots) {
        if (Object.prototype.hasOwnProperty.call(slots, n)) {
          slots[n].forEach(function (s) { out.push({ name: n, id: s.id, pluginId: s.pluginId }); });
        }
      }
      return out;
    }
  };
  QP.chat = chatNamespace;
  QP.audit = {
    overrides: function () { return auditLog; }
  };
  QP.memoryBackends = {
    register: function () { return makeDispose(function () {}); }
  };
  // 旧版入口（agent-kanban 等手写 IIFE 插件在用）：route.add 的便捷包装
  QP.registerRoutes = function (pluginId, rs) {
    (rs || []).forEach(function (r) {
      addRoute(pluginId, {
        id: 'legacy:' + pluginId + ':' + String(r.path).replace(/^\//, ''),
        path: r.path,
        component: r.component,
        label: r.label || r.path,
        icon: r.icon,
        priority: r.priority
      });
    });
    console.info('[plugin:' + pluginId + '] registerRoutes → ' + (rs || []).length + ' route(s)');
  };
  QP.registerToolRender = function (pluginId, renderers) {
    var list = chatLists.toolRender;
    Object.keys(renderers || {}).forEach(function (name) {
      list.push({ pluginId: pluginId, item: { name: name, render: renderers[name] } });
    });
  };

  // ── React shell ─────────────────────────────────────────────────────────
  var React = window.React;
  var ReactDOM = window.ReactDOM;
  var antd = window.antd;
  var h = React.createElement;

  var darkMode = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  (function () {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    // 深浅色切换后须重渲染：antd 主题算法在 AppShell 构建时取 darkMode，
    // 不通知注册表则主题停在初始值（mounted 前切换由首帧自然覆盖）
    var onChange = function (e) {
      darkMode = e.matches;
      if (mounted) {
        notify();
      }
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  })();

  function useMedia(query) {
    var get = function () { return window.matchMedia(query).matches; };
    return React.useSyncExternalStore(function (cb) {
      var mq = window.matchMedia(query);
      var onChange = function () { cb(); };
      if (mq.addEventListener) mq.addEventListener('change', onChange);
      else if (mq.addListener) mq.addListener(onChange);
      return function () {
        if (mq.removeEventListener) mq.removeEventListener('change', onChange);
        else if (mq.removeListener) mq.removeListener(onChange);
      };
    }, get, get);
  }

  function useRegistryVersion() {
    return React.useSyncExternalStore(subscribe, getVersion, getVersion);
  }

  function ErrorBoundary(props) {
    React.Component.call(this, props);
    this.state = { error: null };
  }
  ErrorBoundary.prototype = Object.create(React.Component.prototype);
  ErrorBoundary.prototype.componentDidCatch = function (error) { this.setState({ error: error }); };
  ErrorBoundary.prototype.render = function () {
    if (this.state.error) {
      var msg = String((this.state.error && this.state.error.message) || this.state.error);
      return h(antd.Result, {
        status: 'error',
        title: '插件运行出错',
        subTitle: msg,
        extra: h(antd.Button, { type: 'primary', onClick: function () { window.location.reload(); } }, '重新加载')
      });
    }
    return this.props.children;
  };

  function slotNode(name) {
    var list = slots[name] || [];
    var out = [];
    for (var i = 0; i < list.length; i++) {
      try {
        var node = list[i].render();
        if (node != null) out.push(h(React.Fragment, { key: list[i].id }, node));
      } catch (e) {
        console.warn('[slot:' + name + '] render 失败', e);
      }
    }
    return out.length > 0 ? h(React.Fragment, null, out) : null;
  }

  function routePage(route, key) {
    var Comp = route.component;
    if (route.wrapper) {
      var Wrapped = route.wrapper(Comp);
      Comp = Wrapped;
    }
    return h(ErrorBoundary, { key: key }, h(Comp, null));
  }

  // 当前路由以 location.hash 为单一事实来源（多路由菜单点击 → 改 hash → hashchange
  // → notify 重渲染）；hash 为空时落第一个路由。
  function currentPathOf(sorted) {
    var fromHash = window.location.hash.slice(1);
    if (fromHash) {
      for (var i = 0; i < sorted.length; i++) {
        if (sorted[i].path === fromHash) return fromHash;
      }
    }
    // PawApp 单页：入口路由（manifest meta.pawapp.entry_page）优先；未注册则落首路由
    if (PAWAPP_ROUTE) {
      for (var j = 0; j < sorted.length; j++) {
        if (sorted[j].path === PAWAPP_ROUTE) return PAWAPP_ROUTE;
      }
    }
    return sorted.length > 0 ? sorted[0].path : '';
  }

  function AppShell() {
    useRegistryVersion(); // 注册变化 / 插件加载状态变化 → 重渲染
    var isMobile = useMedia('(max-width: 767px)');
    var isWide = useMedia('(min-width: 1200px)');
    var sorted = routes.slice().sort(function (a, b) {
      return (a.priority - b.priority) || (a.path < b.path ? -1 : 1);
    });
    var hasRoutes = sorted.length > 0;
    // PawApp（meta.pawapp）强制单页：多路由注册（PawApp /apps/ + 侧栏 /plugin/）
    // 不出左侧菜单壳（Sider / drawer / ☰）——本地宿主是单页容器
    var single = sorted.length === 1 || PAWAPP;
    var pluginErr = window.__qpwPluginError || '';
    var drawerOpen = React.useState(false);
    var setDrawerOpen = drawerOpen[1];

    var currentPath = currentPathOf(sorted);
    var currentRoute = null;
    for (var i = 0; i < sorted.length; i++) {
      if (sorted[i].path === currentPath) { currentRoute = sorted[i]; break; }
    }

    var chromeBg = darkMode ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.82)';
    var chromeLine = darkMode ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.06)';

    var menuItems = sorted.map(function (r) {
      return {
        key: r.path,
        label: r.label,
        icon: r.icon ? h('span', { style: { fontSize: 15 } }, r.icon) : undefined
      };
    });
    var menu = h(antd.Menu, {
      mode: 'inline',
      selectedKeys: [currentPath],
      items: menuItems,
      onClick: function (info) { window.location.hash = info.key; },
      style: { borderRight: 0 }
    });

    // 宿主不再自绘 web 标题栏：端侧 HdsNavDestination 已提供标题栏（返回键 / 全屏键 / 应用名），
    // 插件页内再铺一道即"双标题栏"。插件注册的 header 槽（logo/left/right）随旧标题栏一并移除。
    // 移动端多路由菜单的 ☰ 触发器改为左上角浮动按钮（不再依赖标题栏）。
    var drawerTrigger = !single && hasRoutes && isMobile ? h('div', {
      style: {
        position: 'absolute', top: 10, left: 10, zIndex: 20,
        width: 32, height: 32, borderRadius: 9,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 15, lineHeight: '15px',
        color: darkMode ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.65)',
        background: chromeBg,
        backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
        border: '1px solid ' + chromeLine
      },
      onClick: function () { setDrawerOpen(true); }
    }, '☰') : null;

    // 内容区三态：加载中 / 加载失败 / 路由页
    var content;
    if (!hasRoutes) {
      if (pluginErr) {
        content = h('div', { style: { flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 } },
          h(antd.Result, {
            status: 'warning',
            title: '插件未能运行',
            subTitle: pluginErr,
            extra: h(antd.Button, { type: 'primary', onClick: function () {
              console.error('[pluginhost] 点击重试，重新加载页面');
              window.location.reload();
            } }, '重试')
          }));
      } else {
        content = h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 } },
          h(antd.Spin, { size: 'large' }),
          h('div', { style: { fontSize: 13, opacity: 0.55 } }, '插件加载中…'));
      }
    } else {
      content = routePage(currentRoute, currentRoute.id);
    }

    var sider = hasRoutes && !single
      ? h(antd.Layout.Sider, {
          width: 220,
          collapsedWidth: 64,
          breakpoint: isWide ? false : 'lg',
          collapsible: !isWide,
          theme: 'light',
          style: { overflow: 'auto' }
        }, menu)
      : null;

    var drawer = hasRoutes && !single
      ? h(antd.Drawer, {
          open: drawerOpen[0],
          onClose: function () { setDrawerOpen(false); },
          placement: 'left',
          width: 240,
          styles: { body: { padding: '12px 8px' } }
        }, menu)
      : null;

    var shell = isMobile ? (
      h(antd.Layout, { style: { height: '100%', display: 'flex', flexDirection: 'column' } },
        h(antd.Layout.Content, { style: { flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' } }, content),
        drawer)
    ) : (
      h(antd.Layout, { style: { height: '100%' } },
        sider,
        h(antd.Layout, { style: { minHeight: 0, display: 'flex', flexDirection: 'column' } },
          h(antd.Layout.Content, {
            style: { flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }
          }, content)))
    );

    return h(antd.ConfigProvider, {
      theme: { algorithm: darkMode ? antd.theme.darkAlgorithm : antd.theme.defaultAlgorithm }
    },
      h('div', { style: { height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' } },
        shell,
        drawerTrigger,
        slotNode('content.statusBar') ? h('div', { style: { padding: '8px 16px', borderTop: '1px solid ' + chromeLine } }, slotNode('content.statusBar')) : null,
        slotNode('overlay.global')
      )
    );
  }

  // 顶层异常捕获：经典 script 的运行时错误不触发 onerror（那只捕加载失败），
  // 会静默吞掉 → 「未注册任何页面」无从定位；统一经 console.error 桥到端侧日志。
  window.addEventListener('error', function (e) {
    console.error('[pluginhost] 页面脚本异常: ' + (e && e.message ? e.message : String(e)) +
      ' @ ' + (e && e.filename ? e.filename : '?') + ':' + (e && e.lineno ? e.lineno : '?'));
  });
  window.addEventListener('unhandledrejection', function (e) {
    console.error('[pluginhost] 未捕获的 Promise 拒绝: ' +
      (e && e.reason && e.reason.message ? e.reason.message : String(e && e.reason)));
  });

  // createRoot 挂在 ReactDOM 上（React 18 UMD 不导出它）：误查 React 会判为不存在
  // → rootState 为 null，首帧即抛错黑屏（真机 onConsole 实测坐实）。
  var rootState = ReactDOM.createRoot ? ReactDOM.createRoot(document.getElementById('root')) : null;
  var mounted = false;
  window.addEventListener('hashchange', function () {
    if (mounted) notify();
  });

  function boot() {
    console.error('[pluginhost] boot: paw_app=' + APP_ID + ' entry=' + ENTRY);
    rootState.render(h(AppShell, null));
    mounted = true;
    loadPlugin();
  }

  // ── 插件加载：优先 Blob + dynamic import（console 同口径）；失败回退经典 script ──
  var pluginTimer = null;
  function pluginError(message) {
    if (pluginTimer) { clearTimeout(pluginTimer); pluginTimer = null; }
    if (routes.length > 0) return; // 已注册过路由 → 不算失败
    window.__qpwPluginError = message;
    notify();
  }
  function scheduleRouteCheck() {
    pluginTimer = setTimeout(function () {
      if (routes.length === 0) pluginError('插件加载后未注册任何页面（可能仅含后端，或入口路径不正确）');
    }, 8000);
  }
  // 模块执行：源码文本 → Blob URL → import（与 console 的 http 路径同一管线）
  function runModule(text) {
    var blobUrl = URL.createObjectURL(new Blob([text], { type: 'text/javascript' }));
    return import(blobUrl).then(function () {
      URL.revokeObjectURL(blobUrl);
    }, function (e) {
      URL.revokeObjectURL(blobUrl);
      throw e;
    });
  }

  // 端侧文件读取桥（javaScriptProxy：window.qpwFile.readPluginFile → 文件内容 base64）。
  // ArkWeb 对 file:// 的 fetch 被 CORS 拦截（官方 scheme 白名单不含 file），ESM 形态的
  // bundle 走不了 fetch→Blob→import；由端侧读沙箱文件回传，按 data: URL 模块执行
  //（官方 CORS scheme 白名单含 data，任意源可载；blob: 不在白名单内不作首选）。读取失败返回 null。
  function nativeReadB64(rel) {
    if (window.qpwFile && typeof window.qpwFile.readPluginFile === 'function') {
      try {
        var b64 = window.qpwFile.readPluginFile(rel);
        if (typeof b64 === 'string' && b64.length > 0) return b64;
      } catch (e) {
        console.warn('[pluginhost] 端侧读取桥调用失败：', e);
      }
    }
    return null;
  }

  function classicScript(src) {
    var s = document.createElement('script');
    s.src = src;
    s.onload = function () { scheduleRouteCheck(); };
    s.onerror = function () { pluginError('插件脚本加载失败：' + ENTRY); };
    document.body.appendChild(s);
  }

  function loadPlugin() {
    if (!APP_ID || !ENTRY) {
      pluginError('缺少插件入口参数（paw_app / qpw_entry）');
      return;
    }
    var src = 'plugins/' + encodeURIComponent(APP_ID) + '/' + ENTRY.split('/').map(encodeURIComponent).join('/');
    console.error('[pluginhost] loadPlugin: ' + src);
    // 桥用磁盘原样相对路径（script src 才做 URL 编码）
    var rel = 'plugins/' + APP_ID + '/' + ENTRY;
    fetch(src, { headers: { 'Accept': 'text/javascript' } })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
      })
      .then(function (text) {
        runModule(text).then(function () {
          scheduleRouteCheck();
        }, function (importErr) {
          console.warn('[pluginhost] 模块执行失败，回退经典 script：', importErr);
          classicScript(src);
        });
      }, function (fetchErr) {
        // fetch 不可用（file:// 被 CORS 拦截）→ 端侧读取桥补源码，按 data: 模块执行
        var b64 = null;
        try { b64 = nativeReadB64(rel); } catch (e) { b64 = null; }
        if (b64 !== null) {
          console.warn('[pluginhost] fetch 不可用，改用端侧文件读取（data: 模块）：', fetchErr);
          import('data:text/javascript;base64,' + b64).then(function () {
            scheduleRouteCheck();
          }, function (importErr) {
            console.warn('[pluginhost] data: 模块执行失败，回退经典 script：', importErr);
            classicScript(src);
          });
          return;
        }
        // 无桥可读 → 经典 script 回退（仅非 ESM 的 IIFE/CJS bundle 可跑）
        console.warn('[pluginhost] 模块方式加载失败，回退经典 script：', fetchErr);
        classicScript(src);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
