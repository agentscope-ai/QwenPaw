const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const DEFAULT_PROPOSAL_PATH = 'design/KG/ImplementationToIntentTraceProposal.json';
const TRACE_PROPOSAL_SCHEMA_PATH = 'schema/ImplementationToIntentTraceProposal.schema.json';

function main() {
    const proposalPath = process.argv[2] || DEFAULT_PROPOSAL_PATH;
    const errors = validateTraceProposal(proposalPath);

    if (errors.length > 0) {
        console.error('Trace proposal validation failed:');
        for (const error of errors) {
            console.error(`- ${error}`);
        }
        process.exit(1);
    }

    console.log(`Trace proposal validation passed for: ${proposalPath}`);
}

function validateTraceProposal(proposalPath) {
    const errors = [];
    const schemaAbsolutePath = path.join(repoRoot, TRACE_PROPOSAL_SCHEMA_PATH);
    if (!fs.existsSync(schemaAbsolutePath)) {
        errors.push(`schema file is missing at ${TRACE_PROPOSAL_SCHEMA_PATH}`);
        return errors;
    }

    const proposalAbsolutePath = path.join(repoRoot, proposalPath.replace(/[\\/]+/g, path.sep));
    if (!fs.existsSync(proposalAbsolutePath)) {
        errors.push(`proposal file is missing at ${proposalPath}`);
        return errors;
    }

    const document = readJson(proposalAbsolutePath, proposalPath, errors);
    if (!document) {
        return errors;
    }

    requireExact(document, 'proposalType', 'implementation-to-intent-trace', errors, proposalPath);
    requireString(document, 'generatedAt', errors, proposalPath);
    requireExact(document, 'sourceAgent', 'ImplementationDesign', errors, proposalPath);
    requireExact(document, 'targetAgent', 'IntentionDesign', errors, proposalPath);
    requireExact(document, 'lifecycle', 'temporary-trace-proposal', errors, proposalPath);

    const graphPath = requireString(document, 'sourceIntentGraphPath', errors, proposalPath);
    if (graphPath) {
        ensureRepoPathExists(graphPath, `${proposalPath}.sourceIntentGraphPath`, errors);
    }

    const implementationContracts = requireStringArray(document, 'implementationContracts', true, errors, proposalPath);
    if (Array.isArray(implementationContracts)) {
        implementationContracts.forEach((contractPath, index) => {
            ensureRepoPathExists(contractPath, `${proposalPath}.implementationContracts[${index}]`, errors);
        });
    }

    const anchorProposals = requireArray(document, 'anchorProposals', true, errors, proposalPath);
    if (Array.isArray(anchorProposals)) {
        anchorProposals.forEach((anchor, index) => validateAnchorProposal(anchor, `${proposalPath}.anchorProposals[${index}]`, errors));
    }

    return errors;
}

function validateAnchorProposal(anchor, prefix, errors) {
    requireString(anchor, 'intentElementId', errors, prefix);
    requireString(anchor, 'implementationElementName', errors, prefix);
    const implementationElementKind = requireString(anchor, 'implementationElementKind', errors, prefix);
    if (implementationElementKind && ![
        'stable-directory',
        'contract-file',
        'explicit-test-entry',
        'critical-guardrail',
        'runtime-component',
        'schema-contract',
        'mcp-tool',
        'command',
    ].includes(implementationElementKind)) {
        errors.push(`${prefix}.implementationElementKind has unsupported value '${implementationElementKind}'`);
    }

    const implementsType = requireString(anchor, 'implementsType', errors, prefix);
    if (implementsType && !['direct', 'indirect'].includes(implementsType)) {
        errors.push(`${prefix}.implementsType must be 'direct' or 'indirect'`);
    }

    requireString(anchor, 'tracePurpose', errors, prefix);
    const contractPaths = requireStringArray(anchor, 'contractPaths', true, errors, prefix);
    if (Array.isArray(contractPaths)) {
        contractPaths.forEach((contractPath, index) => {
            ensureRepoPathExists(contractPath, `${prefix}.contractPaths[${index}]`, errors);
        });
    }
    const contextEntryPoints = requireStringArray(anchor, 'contextEntryPoints', true, errors, prefix);
    if (Array.isArray(contextEntryPoints)) {
        contextEntryPoints.forEach((entryPoint, index) => {
            ensureRepoPathExists(entryPoint, `${prefix}.contextEntryPoints[${index}]`, errors);
        });
    }
    requireStringArray(anchor, 'excludedDetails', true, errors, prefix);
}

function readJson(filePath, label, errors) {
    try {
        return JSON.parse(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
    } catch (error) {
        errors.push(`failed to parse ${label}: ${String(error)}`);
        return undefined;
    }
}

function requireExact(object, key, expectedValue, errors, prefix) {
    const value = requireString(object, key, errors, prefix);
    if (value && value !== expectedValue) {
        errors.push(`${prefix}.${key} must be '${expectedValue}'`);
    }
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

function ensureRepoPathExists(relativePath, label, errors) {
    const normalized = relativePath.replace(/[\\/]+/g, path.sep);
    const absolutePath = path.join(repoRoot, normalized);
    if (!fs.existsSync(absolutePath)) {
        errors.push(`${label} points to a missing path: ${relativePath}`);
    }
}

if (require.main === module) {
    main();
}

module.exports = {
    validateTraceProposal,
};
