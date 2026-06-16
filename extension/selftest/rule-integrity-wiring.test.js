/**
 * Extension wiring check for the built-in tool rule integrity self-test net.
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

const manifest = readJson('extension/rule-integrity-selftest.manifest.json');
const unitTestBody = read('extension/rule_integrity/tests/test_rules_integrity.py');
const integrationBody = read('extension/rule_integrity/tests/test_integration_entry.py');

assert.strictEqual(manifest.name, 'rule-integrity-selftest');

for (const layerName of ['wiring', 'frontend']) {
    const layer = manifest.layers[layerName];
    for (const target of layer.targets) {
        const relative = layerName === 'frontend' ? path.join('console', target) : target;
        assert.ok(exists(relative), `missing ${layerName} target: ${relative}`);
    }
}

for (const target of manifest.layers.backend.targets) {
    assert.ok(exists(target.module), `missing backend module: ${target.module}`);
    const body = target.module.includes('integration_entry') ? integrationBody : unitTestBody;
    for (const testName of target.tests || []) {
        const marker = `def ${testName}`;
        assert.ok(body.includes(marker), `backend test not found: ${marker}`);
    }
}

const requiredWiring = [
    'extension/rule_integrity/host_bridge.py',
    'extension/rule_integrity/verifier.py',
    'extension/rule_integrity/repair.py',
    'extension/rule_integrity/routes.py',
    'extension/rule_integrity/schemas.py',
    'extension/rule_integrity/startup.py',
    'extension/rule_integrity/runtime.py',
    'extension/rule_integrity/watch_service.py',
    'extension/rule_integrity/sse_hub.py',
    'extension/rule_integrity/tests/integration_harness.py',
    'src/qwenpaw/security/rule_integrity_bridge.py',
    'src/qwenpaw/security/tool_guard/rules_integrity.py',
    'src/qwenpaw/security/tool_guard/rules/rules_manifest.json',
    'src/qwenpaw/security/tool_guard/rules/rules_manifest.sig',
    'src/qwenpaw/security/tool_guard/rules/dangerous_shell_commands.yaml',
    'extension/rule_integrity/scripts/update_tool_rule_manifest.py',
    'scripts/update_tool_rule_manifest.py',
    'console/src/extension/rule_integrity/api/client.ts',
    'console/src/extension/rule_integrity/hooks/useRuleIntegrity.ts',
    'console/src/extension/rule_integrity/hooks/useRuleIntegrityWatch.ts',
    'console/src/extension/rule_integrity/components/RuleIntegrityPassiveCard.tsx',
    'console/src/pages/Settings/Security/useToolGuard.ts',
    'console/src/pages/Settings/Security/useSecurityPage.ts',
    'console/src/pages/Settings/Security/components/IntegrityProtectionSection.tsx',
];

for (const filePath of requiredWiring) {
    assert.ok(exists(filePath), `rule integrity wiring file missing: ${filePath}`);
}

const appBody = read('src/qwenpaw/app/_app.py');
assert.ok(appBody.includes('run_rule_integrity_startup_check'), 'app lifespan must run rule integrity startup check');
assert.ok(appBody.includes('run_rule_integrity_runtime'), 'app lifespan must run rule integrity runtime');
const configBody = read('src/qwenpaw/app/routers/config.py');
assert.ok(configBody.includes('get_rule_integrity_router'), 'config router must include rule integrity delivery router');

const routesBody = read('extension/rule_integrity/routes.py');
assert.ok(routesBody.includes('get_tool_guard_rules_integrity'), 'extension routes must expose integrity status');
assert.ok(routesBody.includes('watch_tool_guard_rules_integrity'), 'extension routes must expose integrity watch SSE');
assert.ok(routesBody.includes('repair_tool_guard_rules_integrity'), 'extension routes must expose repair endpoint');
assert.ok(routesBody.includes('check_integrity_rule_entry'), 'extension routes must expose passive check endpoint');

const toolGuardHook = read('console/src/pages/Settings/Security/useToolGuard.ts');
assert.ok(toolGuardHook.includes('useRuleIntegrity'), 'useToolGuard must compose rule integrity hook');

const integritySection = read('console/src/pages/Settings/Security/components/IntegrityProtectionSection.tsx');
assert.ok(integritySection.includes('RuleIntegrityPassiveCard'), 'IntegrityProtectionSection must compose rule integrity card');

const scenarioIds = new Set(manifest.scenarios.map((item) => item.id));
for (const scenarioId of ['sec-e2e-029', 'ip-e2e-005', 'RI-UI-ENTRY']) {
    assert.ok(scenarioIds.has(scenarioId), `manifest scenario missing: ${scenarioId}`);
}

console.log(
    `rule-integrity-wiring: manifest v${manifest.version} ok ` +
        `(unit module + integration entry, ${manifest.layers.frontend.targets.length} frontend suite)`,
);
