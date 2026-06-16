/**
 * Extension wiring check for the File baseline self-test net.
 * Ensures manifest targets, host bridges, and scenario markers stay aligned.
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..', '..');

function read(relativePath) {
    return fs.readFileSync(path.join(repoRoot, ...relativePath.split('/')), 'utf8');
}

function readJson(relativePath) {
    return JSON.parse(read(relativePath));
}

function exists(relativePath) {
    return fs.existsSync(path.join(repoRoot, ...relativePath.split('/')));
}

const manifest = readJson('scripts/file-baseline-selftest.manifest.json');

function loadBackendModuleBody(modulePath) {
    if (!exists(modulePath)) {
        return null;
    }
    return read(modulePath);
}

function backendTestMarker(testName) {
    if (testName.includes('::')) {
        const methodName = testName.split('::').pop();
        return `def ${methodName}`;
    }
    return `def ${testName}`;
}

assert.strictEqual(manifest.name, 'file-baseline-selftest');

for (const layerName of ['wiring', 'frontend']) {
    const layer = manifest.layers[layerName];
    assert.ok(Array.isArray(layer.targets) && layer.targets.length > 0, `${layerName} targets missing`);
    for (const target of layer.targets) {
        const relative = layerName === 'frontend' ? path.join('console', target) : target;
        assert.ok(exists(relative), `missing ${layerName} target: ${relative}`);
    }
}

for (const target of manifest.layers.backend.targets) {
    assert.ok(exists(target.module), `missing backend module: ${target.module}`);
    const body = loadBackendModuleBody(target.module);
    assert.ok(body, `missing backend module body for: ${target.module}`);
    for (const testName of target.tests || []) {
        const marker = backendTestMarker(testName);
        assert.ok(body.includes(marker), `backend test not found: ${target.module}::${testName}`);
    }
}

const requiredWiring = [
    'extension/file_baseline/emitter.py',
    'extension/file_baseline/service.py',
    'extension/file_baseline/host_bridge.py',
    'extension/file_baseline/workspace_browse.py',
    'src/qwenpaw/security/extension_host.py',
    'src/qwenpaw/security/file_baseline_bridge.py',
    'src/qwenpaw/app/routers/file_baseline_routes.py',
    'console/src/extension/file_baseline/components/WorkspaceProtectableFilePickerModal.tsx',
    'console/src/extension/file_baseline/components/FileBaselineDriftAlertNotifier/index.tsx',
    'console/src/pages/Settings/Security/components/IntegrityProtectionSection.tsx',
];

for (const filePath of requiredWiring) {
    assert.ok(exists(filePath), `file baseline wiring file missing: ${filePath}`);
}

const bridgeBody = read('src/qwenpaw/security/file_baseline_bridge.py');
const hostBridgeBody = read('extension/file_baseline/host_bridge.py');
const emitterBody = read('extension/file_baseline/emitter.py');
assert.ok(
    hostBridgeBody.includes('browse_workspace_protectable_files'),
    'file baseline host bridge must wire workspace browse',
);
assert.ok(
    hostBridgeBody.includes('try_guarded_operator_file_write as _try_guarded_operator_file_write'),
    'file baseline host bridge must import operator write delegate',
);
assert.ok(
    !emitterBody.includes('inbox_append'),
    'file baseline emitter must not write inbox events',
);
assert.ok(
    bridgeBody.includes('get_file_baseline_service'),
    'file baseline bridge must re-export service accessor',
);
assert.ok(
    bridgeBody.includes('browse_workspace_protectable_files'),
    'file baseline bridge must re-export workspace browse',
);
const routesBody = read('src/qwenpaw/app/routers/file_baseline_routes.py');
assert.ok(
    routesBody.includes('/security/file-baseline/browse'),
    'file baseline routes must expose workspace browse API',
);
const mainLayoutBody = read('console/src/layouts/MainLayout/index.tsx');
assert.ok(
    mainLayoutBody.includes('FileBaselineDriftAlertNotifier'),
    'MainLayout must mount FileBaselineDriftAlertNotifier',
);
assert.ok(
    mainLayoutBody.includes('<FileBaselineDriftAlertNotifier'),
    'MainLayout must render FileBaselineDriftAlertNotifier element',
);
assert.ok(
    mainLayoutBody.includes('GlobalOperatorApprovalOverlay'),
    'MainLayout must mount GlobalOperatorApprovalOverlay',
);

const indexBody = read('console/src/extension/file_baseline/index.ts');
const requiredPublicExports = [
    'FileBaselineDriftAlertNotifier',
    'GlobalOperatorApprovalOverlay',
    'useFileBaselineDriftWatch',
    'restoreFileBaselineAlert',
    'acceptFileBaselineAlert',
];
for (const symbol of requiredPublicExports) {
    assert.ok(
        indexBody.includes(symbol),
        `file_baseline index.ts must export ${symbol}`,
    );
}

for (const scenario of manifest.scenarios) {
    if (scenario.layer !== 'frontend') {
        continue;
    }
    const targetName = scenario.target;
    const listed = manifest.layers.frontend.targets.some(
        (entry) => entry.includes(targetName),
    );
    assert.ok(
        listed,
        `frontend scenario ${scenario.id} target must be listed in manifest frontend targets: ${targetName}`,
    );
}

const scenarioIds = new Set(manifest.scenarios.map((item) => item.id));
const expectedScenarioIds = [
    'PB-S02',
    'PB-S10',
    'PB-S30',
    'PB-S40',
    'PB-S42',
    'PB-S50',
    'FB-SUI-INBOX',
    'FB-SUI-NOTIFIER',
    'FB-SUI-HOST',
];
for (const scenarioId of expectedScenarioIds) {
    assert.ok(scenarioIds.has(scenarioId), `manifest scenario missing: ${scenarioId}`);
}

const backendTargetCount = manifest.layers.backend.targets.reduce(
    (count, target) => count + (target.tests?.length || 0),
    0,
);

console.log(
    `file-baseline-wiring: manifest v${manifest.version} ok ` +
        `(${backendTargetCount} backend tests across ${manifest.layers.backend.targets.length} modules, ` +
        `${manifest.layers.frontend.targets.length} frontend targets)`,
);
