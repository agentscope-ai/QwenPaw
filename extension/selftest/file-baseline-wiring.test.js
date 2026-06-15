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
const integrationBody = read('tests/integration/security/test_integrity_protection.py');
const shellPreflightBody = read('tests/unit/extension/test_file_baseline_shell_preflight.py');
const postCommandVerifyBody = read('tests/unit/extension/test_file_baseline_post_command_verify.py');
const osReadonlyBody = read('tests/unit/extension/test_file_baseline_os_readonly.py');

const backendModuleBodies = {
    'tests/integration/security/test_integrity_protection.py': integrationBody,
    'tests/unit/extension/test_file_baseline_shell_preflight.py': shellPreflightBody,
    'tests/unit/extension/test_file_baseline_post_command_verify.py': postCommandVerifyBody,
    'tests/unit/extension/test_file_baseline_os_readonly.py': osReadonlyBody,
};

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
    const body = backendModuleBodies[target.module];
    assert.ok(body, `missing backend module body mapping for: ${target.module}`);
    for (const testName of target.tests || []) {
        const marker = `def ${testName}`;
        assert.ok(body.includes(marker), `backend test not found: ${target.module}::${testName}`);
    }
}

const requiredWiring = [
    'extension/file_baseline/emitter.py',
    'extension/file_baseline/service.py',
    'extension/file_baseline/host_bridge.py',
    'src/qwenpaw/security/extension_host.py',
    'src/qwenpaw/security/file_baseline_bridge.py',
    'src/qwenpaw/app/routers/file_baseline_routes.py',
    'console/src/extension/file_baseline/components/FileBaselineDriftAlertNotifier/index.tsx',
    'console/src/extension/file_baseline/lib/alertActions.ts',
    'console/src/pages/Settings/Security/components/IntegrityProtectionSection.tsx',
];

for (const filePath of requiredWiring) {
    assert.ok(exists(filePath), `file baseline wiring file missing: ${filePath}`);
}

const bridgeBody = read('src/qwenpaw/security/file_baseline_bridge.py');
const hostBridgeBody = read('extension/file_baseline/host_bridge.py');
assert.ok(
    hostBridgeBody.includes('push_append'),
    'file baseline host bridge must wire inbox/push emitters',
);
assert.ok(
    bridgeBody.includes('get_file_baseline_service'),
    'file baseline bridge must re-export service accessor',
);

const notifierBody = read('console/src/extension/file_baseline/components/FileBaselineDriftAlertNotifier/index.tsx');
assert.ok(notifierBody.includes('restoreFileBaselineAlert'), 'notifier must call restoreFileBaselineAlert');
assert.ok(notifierBody.includes('acceptFileBaselineAlert'), 'notifier must call acceptFileBaselineAlert');
assert.ok(
    notifierBody.includes('alertActions'),
    'notifier must use shared file baseline actions',
);

const scenarioIds = new Set(manifest.scenarios.map((item) => item.id));
const expectedScenarioIds = [
    'PB-S02',
    'PB-S10',
    'PB-S30',
    'PB-S40',
    'PB-S42',
    'PB-S50',
    'FB-SUI-NOTIFIER',
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
