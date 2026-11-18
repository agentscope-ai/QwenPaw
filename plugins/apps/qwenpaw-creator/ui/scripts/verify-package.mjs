import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const expected = [
  path.join(uiRoot, 'dist', 'index.js'),
  path.join(uiRoot, 'dist', 'app', 'index.html'),
];

for (const file of expected) {
  const content = await readFile(file);
  if (content.length === 0) throw new Error(`packaged file is empty: ${file}`);
}

const entry = await readFile(path.join(uiRoot, 'dist', 'index.js'), 'utf8');
if (entry.includes('__CREATOR_BUILD_ID__')) {
  throw new Error('plugin entry still contains an unresolved build id placeholder');
}
for (const required of ['registerRoutes', '/apps/qwenpaw-creator']) {
  if (!entry.includes(required)) {
    throw new Error(`plugin entry is missing required PawApp route token: ${required}`);
  }
}
for (const forbidden of [
  'slot.replace',
  'creator.content',
  'route.add',
  'menu.add',
  'qwenpaw-creator-standalone',
]) {
  if (entry.includes(forbidden)) {
    throw new Error(`plugin entry still contains legacy host integration: ${forbidden}`);
  }
}

const listeners = new Map();
const effects = [];
const frameMessages = [];
const frameWindow = {
  postMessage(message) {
    frameMessages.push(message);
  },
};
let iframeProps;
let routeRegistration;
let replacedUrl = null;
const location = {
  pathname: '/apps/qwenpaw-creator',
  search: '',
  hash: '#/project/project-one/plan',
};
const React = {
  useRef(initialValue) {
    return { current: initialValue };
  },
  useEffect(effect) {
    effects.push(effect);
  },
  createElement(type, props, ...children) {
    if (typeof type === 'function') return type(props ?? {});
    if (type === 'iframe') {
      iframeProps = props;
      props.ref.current = { contentWindow: frameWindow };
    }
    return { type, props, children };
  },
};
const browserWindow = {
  location,
  history: {
    state: null,
    replaceState(_state, _title, url) {
      replacedUrl = url;
      location.hash = url.slice(url.indexOf('#'));
    },
  },
  addEventListener(type, listener) {
    listeners.set(type, listener);
  },
  removeEventListener(type) {
    listeners.delete(type);
  },
  QwenPaw: {
    host: {
      React,
      getApiUrl(apiPath) {
        return `/api${apiPath}`;
      },
    },
    registerRoutes(pluginId, routes) {
      routeRegistration = { pluginId, routes };
    },
  },
};

vm.runInNewContext(entry, {
  URL,
  console,
  window: browserWindow,
});
if (routeRegistration?.pluginId !== 'qwenpaw-creator') {
  throw new Error('plugin entry did not self-register under the qwenpaw-creator id');
}
const appRoute = routeRegistration.routes?.find(
  (route) => route.path === '/apps/qwenpaw-creator',
);
if (!appRoute || typeof appRoute.component !== 'function') {
  throw new Error('plugin entry did not register the /apps/qwenpaw-creator route');
}
const rendered = React.createElement(appRoute.component, {});
const cleanups = effects.map((effect) => effect()).filter(Boolean);
if (!iframeProps?.src.endsWith('#/project/project-one/plan')) {
  throw new Error(`iframe did not restore the host deep link: ${iframeProps?.src}`);
}
if (!/\?v=[0-9a-f]{12}#/.test(iframeProps.src)) {
  throw new Error(`iframe is missing a content-derived build id: ${iframeProps.src}`);
}
if (iframeProps.style.height !== '100%') {
  throw new Error('iframe does not fill the Creator app container');
}
if (
  rendered?.props?.style?.width !== '100%' ||
  rendered?.props?.style?.height !== '100%' ||
  rendered?.props?.style?.position !== undefined
) {
  throw new Error('Creator app container must fill the App Center embed frame');
}

listeners.get('message')({
  source: frameWindow,
  data: {
    type: 'qwenpaw-creator:navigation',
    path: '/project/project-two/assets?selected=asset-one',
  },
});
if (replacedUrl !== '/apps/qwenpaw-creator#/project/project-two/assets?selected=asset-one') {
  throw new Error(`Creator navigation escaped the fixed host route: ${replacedUrl}`);
}

location.hash = '#/project/project-three/plan';
listeners.get('hashchange')();
const restored = frameMessages.at(-1);
if (
  restored?.type !== 'qwenpaw-creator:restore-route' ||
  restored?.path !== '/project/project-three/plan'
) {
  throw new Error('host hash navigation was not restored into the Creator iframe');
}
for (const cleanup of cleanups) cleanup();

process.stdout.write('Creator PawApp plugin package verified.\n');
