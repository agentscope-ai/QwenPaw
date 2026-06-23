const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const SYSTEM_ARCHITECTURE_PATH = 'design/KG/SystemArchitecture.json';
const SUPPORTED_ACCEPTANCE_ENTRY_EXTENSIONS = new Set(['.js', '.cjs', '.mjs', '.py']);
const DISALLOWED_ACCEPTANCE_CRITERIA_PATTERNS = [
    /^\s*(?:node|npm|npx|pnpm|yarn|python|py|bun)\b/i,
    /^\s*(?:\.\\|\.\/)?[^\s]+\s+[^:]+/i,
    /[`'"|;&]/,
];

const HANDOFFS = {
    'intent-to-implementation': {
        filePath: 'design/KG/IntentToImplementationHandoff.json',
        schemaPath: 'schema/IntentToImplementationHandoff.schema.json',
        validate: validateIntentToImplementation,
    },
    'implementation-to-coding': {
        filePath: 'design/KG/ImplementationToCodingHandoff.json',
        schemaPath: 'schema/ImplementationToCodingHandoff.schema.json',
        validate: validateImplementationToCoding,
    },
};

function main() {
    const stage = process.argv[2];
    const stages = stage ? [stage] : Object.keys(HANDOFFS);
    const errors = [];

    for (const currentStage of stages) {
        const config = HANDOFFS[currentStage];
        if (!config) {
            errors.push(`Unknown stage '${currentStage}'. Expected one of: ${Object.keys(HANDOFFS).join(', ')}`);
            continue;
        }
        validateStage(currentStage, config, errors);
    }

    if (errors.length > 0) {
        console.error('Stage handoff validation failed:');
        for (const error of errors) {
            console.error(`- ${error}`);
        }
        process.exit(1);
    }

    console.log(`Stage handoff validation passed for: ${stages.join(', ')}`);
}

function validateStage(stage, config, errors) {
    const handoffAbsolutePath = path.join(repoRoot, config.filePath);
    const schemaAbsolutePath = path.join(repoRoot, config.schemaPath);

    if (!fs.existsSync(schemaAbsolutePath)) {
        errors.push(`${stage}: schema file is missing at ${config.schemaPath}`);
        return;
    }

    if (!fs.existsSync(handoffAbsolutePath)) {
        errors.push(`${stage}: handoff file is missing at ${config.filePath}`);
        return;
    }

    let document;
    try {
        document = JSON.parse(fs.readFileSync(handoffAbsolutePath, 'utf8'));
    } catch (error) {
        errors.push(`${stage}: failed to parse ${config.filePath}: ${String(error)}`);
        return;
    }

    config.validate(document, errors, config.filePath);
}

function validateIntentToImplementation(document, errors, filePath) {
    requireString(document, 'stage', errors, filePath);
    requireString(document, 'generatedAt', errors, filePath);
    requireString(document, 'sourceIntentGraphPath', errors, filePath);
    requireStringArray(document, 'intentElementIds', true, errors, filePath);
    requireStringArray(document, 'frozenBaselines', true, errors, filePath);
    requireStringArray(document, 'requiredImplementationArtifacts', true, errors, filePath);

    const graphPath = requireString(document, 'sourceIntentGraphPath', errors, filePath);
    if (graphPath) {
        ensureRepoPathExists(graphPath, `${filePath}.sourceIntentGraphPath`, errors);
    }

    const testcases = requireArray(document, 'explicitTestcases', true, errors, filePath);
    if (Array.isArray(testcases)) {
        testcases.forEach((testcase, index) => {
            requireString(testcase, 'name', errors, `${filePath}.explicitTestcases[${index}]`);
            requireString(testcase, 'mountedElementId', errors, `${filePath}.explicitTestcases[${index}]`);
            requireString(testcase, 'type', errors, `${filePath}.explicitTestcases[${index}]`);
            requireString(testcase, 'controlPoint', errors, `${filePath}.explicitTestcases[${index}]`);
            requireString(testcase, 'observationPoint', errors, `${filePath}.explicitTestcases[${index}]`);
            requireString(testcase, 'acceptanceBoundary', errors, `${filePath}.explicitTestcases[${index}]`);
            const entryKind = requireString(testcase, 'requiredEntryKind', errors, `${filePath}.explicitTestcases[${index}]`);
            if (entryKind && !['explicit-testcase-entry', 'read-only-contract-update', 'critical-non-explicit-test'].includes(entryKind)) {
                errors.push(`${filePath}.explicitTestcases[${index}].requiredEntryKind must be one of explicit-testcase-entry, read-only-contract-update, critical-non-explicit-test`);
            }
        });
    }

    const questions = document.openQuestions;
    if (Array.isArray(questions)) {
        questions.forEach((question, index) => {
            requireString(question, 'question', errors, `${filePath}.openQuestions[${index}]`);
            requireString(question, 'recommendedAnswer', errors, `${filePath}.openQuestions[${index}]`);
            requireString(question, 'reason', errors, `${filePath}.openQuestions[${index}]`);
        });
    }
}

function validateImplementationToCoding(document, errors, filePath) {
    const graphDocument = loadSystemArchitecture(errors, filePath);
    const acceptanceCriteriaByTestcase = buildAcceptanceCriteriaByTestcase(graphDocument, errors, filePath);

    requireString(document, 'stage', errors, filePath);
    requireString(document, 'generatedAt', errors, filePath);
    const graphPath = requireString(document, 'sourceIntentGraphPath', errors, filePath);
    if (graphPath) {
        ensureRepoPathExists(graphPath, `${filePath}.sourceIntentGraphPath`, errors);
    }

    const implementationContracts = requireStringArray(document, 'implementationContracts', true, errors, filePath);
    if (Array.isArray(implementationContracts)) {
        implementationContracts.forEach((contractPath, index) => {
            ensureRepoPathExists(contractPath, `${filePath}.implementationContracts[${index}]`, errors);
        });
    }

    const explicitEntrypoints = requireArray(document, 'explicitEntrypoints', true, errors, filePath);
    if (Array.isArray(explicitEntrypoints)) {
        explicitEntrypoints.forEach((entry, index) => {
            const testcaseName = requireString(entry, 'testcaseName', errors, `${filePath}.explicitEntrypoints[${index}]`);
            const entryPath = requireString(entry, 'entryPath', errors, `${filePath}.explicitEntrypoints[${index}]`);
            requireString(entry, 'controlPoint', errors, `${filePath}.explicitEntrypoints[${index}]`);
            requireString(entry, 'observationPoint', errors, `${filePath}.explicitEntrypoints[${index}]`);
            const status = requireString(entry, 'initialExecutionStatus', errors, `${filePath}.explicitEntrypoints[${index}]`);
            requireString(entry, 'initialExecutionCommand', errors, `${filePath}.explicitEntrypoints[${index}]`);
            if (entryPath) {
                validateAcceptanceEntryReference(entryPath, `${filePath}.explicitEntrypoints[${index}].entryPath`, errors);
            }
            if (status && !['passed', 'failed'].includes(status)) {
                errors.push(`${filePath}.explicitEntrypoints[${index}].initialExecutionStatus must be 'passed' or 'failed'`);
            }
            if (status === 'failed') {
                requireString(entry, 'failureReason', errors, `${filePath}.explicitEntrypoints[${index}]`);
            }
            if (testcaseName && entryPath) {
                const acceptanceCriteria = acceptanceCriteriaByTestcase.get(testcaseName);
                if (!acceptanceCriteria) {
                    errors.push(`${filePath}.explicitEntrypoints[${index}] testcase '${testcaseName}' is missing from ${SYSTEM_ARCHITECTURE_PATH} or has an empty acceptanceCriteria`);
                } else if (normalizeEntrypointReference(acceptanceCriteria) !== normalizeEntrypointReference(entryPath)) {
                    errors.push(`${filePath}.explicitEntrypoints[${index}] entryPath '${entryPath}' must match ${SYSTEM_ARCHITECTURE_PATH} acceptanceCriteria '${acceptanceCriteria}' for testcase '${testcaseName}'`);
                }
            }
        });
    }

    const criticalTests = requireArray(document, 'criticalNonExplicitTests', false, errors, filePath) || [];
    criticalTests.forEach((test, index) => validateNonExplicitTest(test, `${filePath}.criticalNonExplicitTests[${index}]`, errors));

    const supportingTests = requireArray(document, 'supportingNonExplicitTests', false, errors, filePath) || [];
    supportingTests.forEach((test, index) => validateNonExplicitTest(test, `${filePath}.supportingNonExplicitTests[${index}]`, errors));

    const failureRecordsPath = requireString(document, 'expectedFailureRecordsPath', errors, filePath);
    if (failureRecordsPath) {
        ensureRepoPathExists(failureRecordsPath, `${filePath}.expectedFailureRecordsPath`, errors);
    }

    const codingTargets = requireArray(document, 'codingTargets', true, errors, filePath);
    if (Array.isArray(codingTargets)) {
        codingTargets.forEach((target, index) => {
            requireString(target, 'failureSignal', errors, `${filePath}.codingTargets[${index}]`);
            requireString(target, 'nextAction', errors, `${filePath}.codingTargets[${index}]`);
        });
    }

    const taskExecutionPlan = document.taskExecutionPlan;
    if (!taskExecutionPlan || typeof taskExecutionPlan !== 'object' || Array.isArray(taskExecutionPlan)) {
        errors.push(`${filePath}.taskExecutionPlan must be an object`);
    } else {
        requireString(taskExecutionPlan, 'executionStrategy', errors, `${filePath}.taskExecutionPlan`);
        const tasks = requireArray(taskExecutionPlan, 'tasks', true, errors, `${filePath}.taskExecutionPlan`);
        if (Array.isArray(tasks)) {
            const taskIds = new Set();
            tasks.forEach((task, index) => {
                const prefix = `${filePath}.taskExecutionPlan.tasks[${index}]`;
                const taskId = requireString(task, 'taskId', errors, prefix);
                requireString(task, 'title', errors, prefix);
                requireString(task, 'objective', errors, prefix);
                requireString(task, 'completionSignal', errors, prefix);

                const steps = requireArray(task, 'steps', true, errors, prefix);
                if (Array.isArray(steps)) {
                    steps.forEach((step, stepIndex) => {
                        if (typeof step !== 'string' || step.trim() === '') {
                            errors.push(`${prefix}.steps[${stepIndex}] must be a non-empty string`);
                        }
                    });
                }

                if (taskId) {
                    if (taskIds.has(taskId)) {
                        errors.push(`${prefix}.taskId '${taskId}' must be unique within taskExecutionPlan.tasks`);
                    }
                    taskIds.add(taskId);
                }
            });

            tasks.forEach((task, index) => {
                const dependsOn = Array.isArray(task.dependsOn) ? task.dependsOn : [];
                dependsOn.forEach((dependencyId, dependencyIndex) => {
                    if (typeof dependencyId !== 'string' || dependencyId.trim() === '') {
                        errors.push(`${filePath}.taskExecutionPlan.tasks[${index}].dependsOn[${dependencyIndex}] must be a non-empty string`);
                        return;
                    }
                    if (!taskIds.has(dependencyId)) {
                        errors.push(`${filePath}.taskExecutionPlan.tasks[${index}].dependsOn[${dependencyIndex}] references unknown taskId '${dependencyId}'`);
                    }
                });

                validateOptionalStringArray(task, 'relatedTestcases', `${filePath}.taskExecutionPlan.tasks[${index}]`, errors);
                validateOptionalStringArray(task, 'targetPaths', `${filePath}.taskExecutionPlan.tasks[${index}]`, errors);
            });
        }
    }

    const frozenFiles = requireStringArray(document, 'frozenFiles', true, errors, filePath);
    if (Array.isArray(frozenFiles)) {
        frozenFiles.forEach((frozenFile, index) => {
            ensureRepoPathExists(frozenFile, `${filePath}.frozenFiles[${index}]`, errors);
        });
    }
}

function validateNonExplicitTest(test, prefix, errors) {
    const testPath = requireString(test, 'path', errors, prefix);
    requireString(test, 'controlPoint', errors, prefix);
    requireString(test, 'observationPoint', errors, prefix);
    if (testPath) {
        ensureRepoPathExists(testPath, `${prefix}.path`, errors);
    }
}

function loadSystemArchitecture(errors, filePath) {
    const absolutePath = path.join(repoRoot, SYSTEM_ARCHITECTURE_PATH);
    if (!fs.existsSync(absolutePath)) {
        errors.push(`${filePath}: required graph file is missing at ${SYSTEM_ARCHITECTURE_PATH}`);
        return undefined;
    }

    try {
        return JSON.parse(fs.readFileSync(absolutePath, 'utf8'));
    } catch (error) {
        errors.push(`${filePath}: failed to parse ${SYSTEM_ARCHITECTURE_PATH}: ${String(error)}`);
        return undefined;
    }
}

function buildAcceptanceCriteriaByTestcase(graphDocument, errors, filePath) {
    const mapping = new Map();
    if (!graphDocument || !Array.isArray(graphDocument.elements)) {
        return mapping;
    }

    graphDocument.elements.forEach((element, elementIndex) => {
        if (!Array.isArray(element.testcases)) {
            return;
        }

        element.testcases.forEach((testcase, testcaseIndex) => {
            if (!testcase || typeof testcase.name !== 'string' || testcase.name.trim() === '') {
                return;
            }

            const testcaseName = testcase.name.trim();
            const acceptanceCriteria = typeof testcase.acceptanceCriteria === 'string'
                ? testcase.acceptanceCriteria.trim()
                : '';

            if (!acceptanceCriteria) {
                errors.push(`${filePath}: ${SYSTEM_ARCHITECTURE_PATH}.elements[${elementIndex}].testcases[${testcaseIndex}].acceptanceCriteria must be a non-empty entrypoint string for testcase '${testcaseName}'`);
                return;
            }

            validateAcceptanceEntryReference(
                acceptanceCriteria,
                `${SYSTEM_ARCHITECTURE_PATH}.testcase(${testcaseName}).acceptanceCriteria`,
                errors,
            );

            mapping.set(testcaseName, acceptanceCriteria);
        });
    });

    return mapping;
}

function validateAcceptanceEntryReference(value, label, errors) {
    if (typeof value !== 'string' || value.trim() === '') {
        errors.push(`${label} must be a non-empty string`);
        return;
    }

    const trimmed = value.trim();
    for (const pattern of DISALLOWED_ACCEPTANCE_CRITERIA_PATTERNS) {
        if (pattern.test(trimmed)) {
            errors.push(`${label} must be a single workspace-relative testcase entrypoint, not a descriptive sentence or wrapped command`);
            return;
        }
    }

    const scriptPath = normalizeEntrypointReference(trimmed);
    const extension = path.extname(scriptPath).toLowerCase();
    if (!SUPPORTED_ACCEPTANCE_ENTRY_EXTENSIONS.has(extension)) {
        errors.push(`${label} must point to a single executable entry file (${Array.from(SUPPORTED_ACCEPTANCE_ENTRY_EXTENSIONS).join(', ')}) optionally followed by a pytest ::selector`);
        return;
    }

    ensureRepoPathExists(scriptPath, label, errors);
}

function normalizeEntrypointReference(value) {
    const [scriptPath] = String(value).split('::');
    return scriptPath.replace(/\\/g, '/').replace(/^\.\//, '').trim();
}

function requireString(object, key, errors, prefix) {
    if (!object || typeof object[key] !== 'string' || object[key].trim() === '') {
        errors.push(`${prefix}.${key} must be a non-empty string`);
        return undefined;
    }
    return object[key];
}

function requireArray(object, key, mustHaveItems, errors, prefix) {
    if (!object || !Array.isArray(object[key])) {
        errors.push(`${prefix}.${key} must be an array`);
        return undefined;
    }
    if (mustHaveItems && object[key].length === 0) {
        errors.push(`${prefix}.${key} must not be empty`);
    }
    return object[key];
}

function requireStringArray(object, key, mustHaveItems, errors, prefix) {
    const value = requireArray(object, key, mustHaveItems, errors, prefix);
    if (!Array.isArray(value)) {
        return undefined;
    }
    value.forEach((entry, index) => {
        if (typeof entry !== 'string' || entry.trim() === '') {
            errors.push(`${prefix}.${key}[${index}] must be a non-empty string`);
        }
    });
    return value;
}

function validateOptionalStringArray(object, key, prefix, errors) {
    if (object[key] === undefined) {
        return;
    }

    if (!Array.isArray(object[key])) {
        errors.push(`${prefix}.${key} must be an array`);
        return;
    }

    object[key].forEach((entry, index) => {
        if (typeof entry !== 'string' || entry.trim() === '') {
            errors.push(`${prefix}.${key}[${index}] must be a non-empty string`);
        }
    });
}

function ensureRepoPathExists(relativePath, label, errors) {
    const normalized = relativePath.replace(/[\\/]+/g, path.sep);
    const absolutePath = path.join(repoRoot, normalized);
    if (!fs.existsSync(absolutePath)) {
        errors.push(`${label} points to a missing path: ${relativePath}`);
    }
}

main();