/**
 * Extension wiring check for the Health Check self-test net.
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

const manifest = readJson('scripts/health-check-selftest.manifest.json');
const integrationBody = read('tests/integration/security/test_integrity_protection.py');
const unitBody = read('tests/unit/security/test_health_check_projection.py');

assert.strictEqual(manifest.name, 'health-check-selftest');

for (const layerName of ['wiring', 'frontend']) {
    const layer = manifest.layers[layerName];
    for (const target of layer.targets) {
        const relative = layerName === 'frontend' ? path.join('console', target) : target;
        assert.ok(exists(relative), `missing ${layerName} target: ${relative}`);
    }
}

for (const target of manifest.layers.backend.targets) {
    assert.ok(exists(target.module), `missing backend module: ${target.module}`);
    for (const testName of target.tests || []) {
        const marker = `def ${testName}`;
        const body = target.module.includes('integration') ? integrationBody : unitBody;
        assert.ok(body.includes(marker), `backend test not found: ${marker}`);
    }
}

const requiredWiring = [
    'console/src/extension/health_check/components/HealthCheckSection.tsx',
    'console/src/extension/persona_baseline/components/PersonaDriftAlertNotifier/index.tsx',
    'src/qwenpaw/security/integrity_protection.py',
    'src/qwenpaw/app/routers/integrity_protection_routes.py',
    'src/qwenpaw/app/routers/config.py',
    'console/src/pages/Settings/Security/components/IntegrityCheckSection.tsx',
    'console/src/api/modules/security.ts',
];

for (const filePath of requiredWiring) {
    assert.ok(exists(filePath), `health check wiring file missing: ${filePath}`);
}

const healthSection = read('console/src/extension/health_check/components/HealthCheckSection.tsx');
assert.ok(healthSection.includes('runIntegrityHealthCheckScan'), 'HealthCheckSection must call scan API');
assert.ok(healthSection.includes('runIntegrityHealthCheckFix'), 'HealthCheckSection must call fix API');
assert.ok(healthSection.includes('runCheck'), 'HealthCheckSection must expose single run check control');
assert.ok(healthSection.includes('showIssuesOnly'), 'HealthCheckSection must expose issues-only filter');
assert.ok(healthSection.includes('healthCheckSummary'), 'HealthCheckSection must expose scan summary');

const healthApiClient = read('console/src/extension/health_check/api/client.ts');
const securityApi = read('console/src/api/modules/security.ts');
assert.ok(healthApiClient.includes('/health-check/scan'), 'health check API client must define scan endpoint');
assert.ok(healthApiClient.includes('/health-check/fix'), 'health check API client must define fix endpoint');
assert.ok(securityApi.includes('healthCheckApi'), 'security API must delegate health check to extension client');

const scenarioIds = new Set(manifest.scenarios.map((item) => item.id));
for (const scenarioId of ['HC-S01', 'HC-S05', 'ip-e2e-004', 'HC-DOCTOR']) {
    assert.ok(scenarioIds.has(scenarioId), `manifest scenario missing: ${scenarioId}`);
}

console.log(
    `health-check-wiring: manifest v${manifest.version} ok ` +
        `(integration ${manifest.layers.backend.targets[0].tests.length} tests, ` +
        `${manifest.layers.frontend.targets.length} frontend suites)`,
);
