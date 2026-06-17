const assert = require('assert');
const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..', '..');

const explicitObservationPanelTestcases = [
    {
        testcaseName: 'security-center-event-observation-panel-v1-posture-statistics',
        entryPath: 'tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_summarizes_current_event_posture',
        marker: 'def test_observation_panel_summarizes_current_event_posture',
        harnessMethod: 'observation_panel_summarizes_current_event_posture',
    },
    {
        testcaseName: 'security-center-event-observation-panel-v1-alert-scope',
        entryPath: 'tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_filters_alerts_by_severity',
        marker: 'def test_observation_panel_filters_alerts_by_severity',
        harnessMethod: 'observation_panel_filters_alerts_by_severity',
    },
    {
        testcaseName: 'security-center-event-observation-panel-v1-alert-ordering',
        entryPath: 'tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_sorts_alerts_by_severity_and_occurred_at',
        marker: 'def test_observation_panel_sorts_alerts_by_severity_and_occurred_at',
        harnessMethod: 'observation_panel_sorts_alerts_by_severity_and_occurred_at',
    },
    {
        testcaseName: 'security-center-event-observation-panel-v1-failed-receptions-visible',
        entryPath: 'tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_shows_failed_receptions_in_raw_records',
        marker: 'def test_observation_panel_shows_failed_receptions_in_raw_records',
        harnessMethod: 'observation_panel_shows_failed_receptions_in_raw_records',
    },
    {
        testcaseName: 'security-center-event-observation-panel-v1-alert-to-raw-traceability',
        entryPath: 'tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_links_alert_to_raw_record',
        marker: 'def test_observation_panel_links_alert_to_raw_record',
        harnessMethod: 'observation_panel_links_alert_to_raw_record',
    },
    {
        testcaseName: 'security-center-event-observation-panel-v1-time-range-consistency',
        entryPath: 'tests/e2e/security_center/test_security_event_observation_panel.py::test_observation_panel_applies_time_range_consistently',
        marker: 'def test_observation_panel_applies_time_range_consistently',
        harnessMethod: 'observation_panel_applies_time_range_consistently',
    },
];

function readText(relativePath) {
    return fs.readFileSync(path.join(repoRoot, ...relativePath.split('/')), 'utf8');
}

function readJson(relativePath) {
    return JSON.parse(readText(relativePath));
}

const graph = readJson('design/KG/SystemArchitecture.json');
const handoff = readJson('design/KG/ImplementationToCodingHandoff.json');
const rootContract = readText('OVERALL_ARCHITECTURE.md');
const deployContract = readText('deploy/ARCHITECTURE.md');
const deployApiContract = readText('deploy/api/ARCHITECTURE.md');
const deployWebContract = readText('deploy/web/ARCHITECTURE.md');
const testsContract = readText('tests/ARCHITECTURE.md');
const architectureContract = readText('tests/architecture/ARCHITECTURE.md');
const e2eContract = readText('tests/e2e/security_center/ARCHITECTURE.md');
const integrationSecurityContract = readText('tests/integration/security/ARCHITECTURE.md');
const webTestBody = readText('tests/e2e/security_center/test_security_event_observation_panel.py');
const harnessBody = readText('tests/integration/security/security_event_harness.py');

for (const explicitTestcase of explicitObservationPanelTestcases) {
    const graphTestcase = (graph.elements || [])
        .flatMap(element => element.testcases || [])
        .find(testcase => testcase.name === explicitTestcase.testcaseName);

    assert.ok(graphTestcase, `SystemArchitecture.json must include ${explicitTestcase.testcaseName}.`);
    assert.strictEqual(
        graphTestcase.acceptanceCriteria,
        explicitTestcase.entryPath,
        `${explicitTestcase.testcaseName} must stay mounted to the frozen explicit entrypoint.`,
    );

    const handoffEntrypoint = (handoff.explicitEntrypoints || []).find(
        entry => entry.testcaseName === explicitTestcase.testcaseName,
    );
    assert.ok(handoffEntrypoint, `Implementation handoff must include ${explicitTestcase.testcaseName}.`);
    assert.strictEqual(handoffEntrypoint.entryPath, explicitTestcase.entryPath);
    assert.strictEqual(
        handoffEntrypoint.initialExecutionStatus,
        'failed',
        `${explicitTestcase.testcaseName} must remain an expected failing Coding/Repair input until implemented.`,
    );

    assert.ok(webTestBody.includes(explicitTestcase.marker), `Missing test marker ${explicitTestcase.marker}.`);
    assert.ok(webTestBody.includes('# // GIVEN'), `${explicitTestcase.testcaseName} must keep GIVEN marker.`);
    assert.ok(webTestBody.includes('# // WHEN'), `${explicitTestcase.testcaseName} must keep WHEN marker.`);
    assert.ok(webTestBody.includes('# // THEN'), `${explicitTestcase.testcaseName} must keep THEN marker.`);
    assert.ok(harnessBody.includes(explicitTestcase.harnessMethod), `Harness must expose ${explicitTestcase.harnessMethod}.`);
}

for (const marker of [
    'Security_Event_Observation_Panel_Gap',
    'Security_Event_Observation_Panel_API_Missing',
    'Security_Event_Observation_Panel_Web_Missing',
    '/security-center/v1/operator/event-observation-panel',
    '/security-event-observation',
    'default_range_is_latest_24h',
    '_observation_panel(None)',
    'backend_received_at',
    '_apply_failed_reception_received_at_baseline',
    'totalAcceptedEvents',
    'highAcceptedEvents',
    'sourceSystemDistribution',
    'eventTypeIdDistribution',
    'alerts',
    'rawRecords',
    'focusedRawRecord',
    'focusSourceSystem',
    'focusEventId',
]) {
    assert.ok(harnessBody.includes(marker), `Observation panel harness must keep marker: ${marker}`);
}

for (const marker of [
    'panel-posture-edr-high-001',
    'panel-debug-001',
    'panel-order-high-newer',
    'panel-failed-illegal-source',
    'panel-trace-high-001',
    'panel-range-1h-high',
    'backend_received_at=_latest_timestamp(minutes_ago=30)',
    'backend_received_at=_latest_timestamp(days_ago=8)',
]) {
    assert.ok(webTestBody.includes(marker), `Business-readable fixture marker must stay frozen: ${marker}`);
}

for (const marker of [
    'Security Event Observation Panel V1',
    'tests/e2e/security_center/test_security_event_observation_panel.py',
    'security-center-event-observation-panel-v1-posture-statistics',
    'security-center-event-observation-panel-v1-time-range-consistency',
]) {
    assert.ok(rootContract.includes(marker), `Root contract must reference ${marker}.`);
}

for (const marker of [
    'GET /security-center/v1/operator/event-observation-panel` without an explicit `range`',
    'GET /security-center/v1/operator/event-observation-panel?range={1h|24h|7d}',
    'focusSourceSystem',
    'focusEventId',
    'selectedRange',
    'totalAcceptedEvents',
    'highAcceptedEvents',
    'rawRecords',
    'focusedRawRecord',
    'backend-generated `receivedAt`',
]) {
    assert.ok(deployApiContract.includes(marker), `deploy/api contract must freeze ${marker}.`);
}

for (const marker of [
    '/security-event-observation',
    'latest 1 hour',
    'latest 24 hours',
    'latest 7 days',
    'HIGH and MEDIUM',
    'sourceSystem plus eventId',
    'backend receivedAt',
]) {
    assert.ok(deployWebContract.includes(marker), `deploy/web contract must freeze ${marker}.`);
}

for (const marker of [
    'observation-panel',
    'tests/e2e/security_center/test_security_event_observation_panel.py',
    'security-event-observation-panel-contract-boundaries.test.js',
]) {
    assert.ok(
        deployContract.includes(marker)
        || testsContract.includes(marker)
        || architectureContract.includes(marker)
        || e2eContract.includes(marker)
        || integrationSecurityContract.includes(marker),
        `Local contracts must reference ${marker}.`,
    );
}
