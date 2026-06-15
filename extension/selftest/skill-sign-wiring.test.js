/**
 * Extension wiring check for skill secure import self-test net.
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

const manifest = readJson('extension/skill-sign-selftest.manifest.json');
const verifierBody = read('extension/skill_sign/tests/test_verifier.py');
const poolImportBody = read('extension/skill_sign/tests/test_pool_import.py');
const integrationBody = read('extension/skill_sign/tests/test_integration_entry.py');

assert.strictEqual(manifest.name, 'skill-sign-selftest');

for (const layerName of ['wiring', 'frontend']) {
    const layer = manifest.layers[layerName];
    for (const target of layer.targets) {
        const relative = layerName === 'frontend' ? path.join('console', target) : target;
        assert.ok(exists(relative), `missing ${layerName} target: ${relative}`);
    }
}

for (const target of manifest.layers.backend.targets) {
    assert.ok(exists(target.module), `missing backend module: ${target.module}`);
    let body = verifierBody;
    if (target.module.includes('integration_entry')) body = integrationBody;
    else if (target.module.includes('pool_import')) body = poolImportBody;
    for (const testName of target.tests || []) {
        const marker = `def ${testName}`;
        assert.ok(body.includes(marker), `backend test not found: ${marker}`);
    }
}

const requiredWiring = [
    'extension/Skill Secure Import Design.md',
    'extension/skill_sign/verifier.py',
    'extension/skill_sign/host_bridge.py',
    'extension/skill_sign/routes.py',
    'extension/skill_sign/pool_import.py',
    'extension/skill_sign/upload.py',
    'extension/skill_sign/constants.py',
    'extension/skill_sign/sign_tool/sign_skill.py',
    'extension/skill_sign/trust/qwenpaw-skill-signing-public.pem',
    'extension/skill_sign/sign_tool/examples/valid/demo-skill/SKILL.md',
    'extension/skill_sign/sign_tool/examples/valid/demo-skill.zip',
    'extension/skill_sign/sign_tool/examples/valid/demo-skill.zip.sig',
    'extension/skill_sign/sign_tool/examples/invalid/tampered-skill.zip',
    'extension/skill_sign/sign_tool/examples/invalid/tampered-skill.zip.sig',
    'src/qwenpaw/security/skill_sign_bridge.py',
    'console/src/extension/skill_sign/api/client.ts',
    'console/src/extension/skill_sign/hooks/useSkillPoolSecureImport.ts',
    'console/src/extension/skill_sign/components/SkillPoolSecureImportButton.tsx',
    'console/src/extension/skill_sign/index.ts',
    'console/src/pages/Settings/SkillPool/index.tsx',
    'console/src/pages/Settings/SkillPool/useSkillPool.tsx',
];

for (const filePath of requiredWiring) {
    assert.ok(exists(filePath), `skill sign wiring file missing: ${filePath}`);
}

const skillsRouter = read('src/qwenpaw/app/routers/skills.py');
assert.ok(
    skillsRouter.includes('get_skill_sign_router'),
    'skills router must include skill sign delivery router',
);
assert.ok(
    !skillsRouter.includes('verify_skill_package(data'),
    'skills router must not embed secure import handler body',
);

const routesBody = read('extension/skill_sign/routes.py');
assert.ok(
    routesBody.includes('/pool/secure-import'),
    'extension routes must expose secure import endpoint',
);

const skillPoolPage = read('console/src/pages/Settings/SkillPool/index.tsx');
assert.ok(
    skillPoolPage.includes('SkillPoolSecureImportButton'),
    'SkillPool page must compose secure import control from extension',
);

const scenarioIds = new Set(manifest.scenarios.map((item) => item.id));
for (const scenarioId of ['ip-e2e-003-entry', 'SS-UI-ENTRY']) {
    assert.ok(scenarioIds.has(scenarioId), `manifest scenario missing: ${scenarioId}`);
}

console.log(
    `skill-sign-wiring: manifest v${manifest.version} ok ` +
        `(verifier + pool import + integration entry, ${manifest.layers.frontend.targets.length} frontend suites)`,
);
