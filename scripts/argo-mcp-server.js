const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

const validatorMcp = require('./validator-mcp-server.js');
const systemArchitectureMcp = require('./systemarchitecture-mcp-server.js');

const HANDOFF_FILES_TO_RESET = [
  ['design', 'KG', 'IntentToImplementationHandoff.json'],
  ['design', 'KG', 'ImplementationToCodingHandoff.json'],
];
const EA_TEMPLATE_PATH_CANDIDATES = [
  ['.opencode', 'customtools', 'EA-model-template.feap'],
  ['.opencode', 'EA-model-template.feap'],
  ['eatool', 'EA-model-template.feap'],
  ['EA-model-template.feap'],
  ['Argo.feap'],
];
const WINDOWS_RESERVED_NAMES = new Set([
  'CON', 'PRN', 'AUX', 'NUL',
  'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
  'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
]);

const VALIDATOR_TOOL_NAMES = new Set([
  'validateSystemArchitecture',
  'validateStageHandoff',
  'validateTraceProposal',
  'runArchitectureTests',
]);
const SYSTEM_ARCHITECTURE_TOOL_NAMES = new Set([
  'getSystemArchitecture',
  'getIntentElementContext',
  'previewSystemArchitectureMutation',
  'applySystemArchitectureMutation',
  'addArchitectureElement',
  'updateArchitectureElement',
  'removeArchitectureElement',
  'addArchitectureRelationship',
  'updateArchitectureRelationship',
  'removeArchitectureRelationship',
  'addArchitectureView',
  'updateArchitectureView',
  'removeArchitectureView',
]);

const TOOLS = [
  {
    name: 'initializeWorkspace',
    description: 'Bootstrap an Argo workspace by copying the EA template target and resetting stage handoff artifacts.',
    inputSchema: {
      type: 'object',
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: 'validateSystemArchitecture',
    description: 'Validate design/KG/SystemArchitecture.json through the repository-native schema and graph validator.',
    inputSchema: {
      type: 'object',
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: 'validateStageHandoff',
    description: 'Validate Argo stage handoff JSON. Use stage intent-to-implementation or implementation-to-coding, or omit to validate all supported stages.',
    inputSchema: {
      type: 'object',
      properties: {
        stage: {
          type: 'string',
          enum: ['intent-to-implementation', 'implementation-to-coding'],
          description: 'Optional handoff stage to validate.',
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'validateTraceProposal',
    description: 'Validate ImplementationToIntentTraceProposal JSON against schema/ImplementationToIntentTraceProposal.schema.json and repository path references.',
    inputSchema: {
      type: 'object',
      properties: {
        proposalPath: {
          type: 'string',
          description: 'Optional proposal path relative to workspace root. Default: design/KG/ImplementationToIntentTraceProposal.json',
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'runArchitectureTests',
    description: 'Execute explicit architecture testcases from the intent graph and refresh design/KG/test-failure-records.json.',
    inputSchema: {
      type: 'object',
      properties: {
        architecturePath: {
          type: 'string',
          description: 'Optional architecture graph path relative to workspace root. Default: design/KG/SystemArchitecture.json',
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'getSystemArchitecture',
    description: 'Start here. read-only tool for inspecting current elements, relationships, views, and ids before planning mutations. Use before preview or focused mutation tools.',
    inputSchema: {
      type: 'object',
      properties: {
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'getIntentElementContext',
    description: 'read-only query that returns an intent subgraph context for one element. Uses ArchiMate semantic dependency traversal with dependencyDepth and dependentDepth, preserving native subgraph elements, relationships, and views.',
    inputSchema: intentElementContextInputSchema(),
  },
  {
    name: 'previewSystemArchitectureMutation',
    description: 'Use before apply for complex or risky changes. Performs a dry-run of one or more mutations, runs schema, graph, view, and ArchiMate 3.2 validation, and does not write the graph.',
    inputSchema: mutationInputSchema(),
  },
  {
    name: 'applySystemArchitectureMutation',
    description: 'Use for multi-step or dependent graph changes that should be validated and written atomically. Prefer focused tools for a single simple add, update, or remove operation.',
    inputSchema: mutationInputSchema(),
  },
  {
    name: 'addArchitectureElement',
    description: 'Use for one element. Creates a new element or adds an existing element to view_ids. view_ids is required so elements never exist outside views.',
    inputSchema: {
      type: 'object',
      required: ['element', 'view_ids'],
      properties: {
        element: { type: 'object' },
        view_ids: { type: 'array', minItems: 1, items: { type: 'string' } },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'updateArchitectureElement',
    description: 'Use for one global element metadata patch. Does not change view membership. Element id and type are immutable; remove and re-add to change them.',
    inputSchema: {
      type: 'object',
      required: ['id', 'patch'],
      properties: {
        id: { type: 'string' },
        patch: { type: 'object' },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'removeArchitectureElement',
    description: 'Use for one element removal. With view_ids, removes only from those views and cascades related relationships in the same views; without view_ids, removes from all views and the graph.',
    inputSchema: {
      type: 'object',
      required: ['id'],
      properties: {
        id: { type: 'string' },
        view_ids: { type: 'array', minItems: 1, items: { type: 'string' } },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'addArchitectureRelationship',
    description: 'Use for one relationship. Creates a new relationship or adds an existing relationship to view_ids. relationship.type is the ArchiMate 3.2 relationship type and is validated against endpoint element types.',
    inputSchema: {
      type: 'object',
      required: ['relationship', 'view_ids'],
      properties: {
        relationship: { type: 'object' },
        view_ids: { type: 'array', minItems: 1, items: { type: 'string' } },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'updateArchitectureRelationship',
    description: 'Use for one global relationship metadata patch, such as name, statement, source_name, or target_name. Relationship id and type are immutable; remove and re-add to change them.',
    inputSchema: {
      type: 'object',
      required: ['id', 'patch'],
      properties: {
        id: { type: 'string' },
        patch: { type: 'object' },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'removeArchitectureRelationship',
    description: 'Use for one relationship removal. With view_ids, removes only from those views; without view_ids, removes from all views and deletes it from the graph.',
    inputSchema: {
      type: 'object',
      required: ['id'],
      properties: {
        id: { type: 'string' },
        view_ids: { type: 'array', minItems: 1, items: { type: 'string' } },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'addArchitectureView',
    description: 'Use for one view. The graph must have exactly one top-level view named SystemArchitecture; all sub-views must attach to an element with parent_element_id.',
    inputSchema: {
      type: 'object',
      required: ['view'],
      properties: {
        view: { type: 'object' },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'updateArchitectureView',
    description: 'Use for one view metadata or membership patch. Keep the one top-level view named SystemArchitecture and attach sub-views to parent elements.',
    inputSchema: {
      type: 'object',
      required: ['view_id', 'patch'],
      properties: {
        view_id: { type: 'string' },
        patch: { type: 'object' },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'removeArchitectureView',
    description: 'Use for one view removal. After removal, every remaining element and relationship must still belong to at least one view.',
    inputSchema: {
      type: 'object',
      required: ['view_id'],
      properties: {
        view_id: { type: 'string' },
        architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      },
      additionalProperties: false,
    },
  },
];

function intentElementContextInputSchema() {
  return {
    type: 'object',
    properties: {
      architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      elementId: { type: 'string' },
      elementName: { type: 'string' },
      profile: {
        type: 'string',
        enum: ['implementation-design', 'coding-repair', 'audit', 'generic-agent'],
        description: 'Default: generic-agent. Affects workContext enrichment only; subgraph shape stays native.',
      },
      dependencyDepth: { type: 'number', description: 'Default: 2. Semantic dependencies needed by the focus element.' },
      dependentDepth: { type: 'number', description: 'Default: 1. Semantic dependents that rely on the focus element.' },
      associationDepth: { type: 'number', description: 'Default: 1. Association neighbors are expanded at least one layer.' },
      associationNeighborDependencyDepth: { type: 'number', description: 'Default: 0. Optional dependency expansion from association neighbors.' },
    },
    additionalProperties: false,
  };
}

function mutationInputSchema() {
  return {
    type: 'object',
    required: ['mutations'],
    properties: {
      architecturePath: { type: 'string', description: 'Default: design/KG/SystemArchitecture.json' },
      mutations: {
        type: 'array',
        minItems: 1,
        items: {
          type: 'object',
          required: ['type'],
          properties: {
            type: {
              type: 'string',
              enum: [
                'addElement',
                'updateElement',
                'removeElement',
                'addRelationship',
                'updateRelationship',
                'removeRelationship',
                'addView',
                'updateView',
                'removeView',
              ],
            },
            element: { type: 'object' },
            relationship: { type: 'object' },
            view: { type: 'object' },
            id: { type: 'string' },
            patch: { type: 'object' },
            view_id: { type: 'string' },
            view_ids: { type: 'array', minItems: 1, items: { type: 'string' } },
            element_ids: { type: 'array', items: { type: 'string' } },
            relationship_ids: { type: 'array', items: { type: 'string' } },
          },
          additionalProperties: false,
        },
      },
    },
    additionalProperties: false,
  };
}

function resolveWorkspaceRoot() {
  return process.env.ARGO_REPO_ROOT
    || process.env.WORKSPACE_FOLDER
    || path.resolve(__dirname, '..');
}

async function callTool(name, args = {}) {
  if (name === 'initializeWorkspace') {
    return toolResult(await initializeWorkspace(resolveWorkspaceRoot()));
  }
  if (VALIDATOR_TOOL_NAMES.has(name)) {
    return validatorMcp.callTool(name, args);
  }
  if (SYSTEM_ARCHITECTURE_TOOL_NAMES.has(name)) {
    return systemArchitectureMcp.callTool(name, args);
  }
  throw new Error(`Unknown tool: ${name}`);
}

async function initializeWorkspace(workspaceRoot) {
  const workspaceName = path.basename(workspaceRoot);
  const createdFiles = [];
  const updatedFiles = [];
  const removedFiles = [];
  const skippedSteps = [];

  const templateSourcePath = resolveTemplateSourcePath(workspaceRoot);
  const targetFeapName = buildTargetFileName(workspaceName);
  const targetFeapPath = path.join(workspaceRoot, targetFeapName);
  if (!fs.existsSync(targetFeapPath)) {
    await fs.promises.copyFile(templateSourcePath, targetFeapPath);
    createdFiles.push(normalizeRelativePath(targetFeapName));
  } else {
    skippedSteps.push(`${normalizeRelativePath(targetFeapName)} already exists`);
  }

  for (const handoffPath of HANDOFF_FILES_TO_RESET) {
    const absolutePath = path.join(workspaceRoot, ...handoffPath);
    if (fs.existsSync(absolutePath)) {
      await fs.promises.rm(absolutePath, { force: true });
      removedFiles.push(normalizeRelativePath(path.relative(workspaceRoot, absolutePath)));
    }
  }

  return {
    workspaceRoot,
    targetFeapName,
    createdFiles,
    updatedFiles,
    removedFiles,
    skippedSteps,
    status: 'ok',
  };
}

function resolveTemplateSourcePath(workspaceRoot) {
  for (const candidate of EA_TEMPLATE_PATH_CANDIDATES) {
    const absolutePath = path.join(workspaceRoot, ...candidate);
    if (fs.existsSync(absolutePath)) {
      return absolutePath;
    }
  }
  throw new Error(`Unable to locate EA template. Checked: ${EA_TEMPLATE_PATH_CANDIDATES.map(candidate => candidate.join('/')).join(', ')}`);
}

function buildTargetFileName(workspaceName) {
  const sanitized = sanitizeFileName(workspaceName) || 'workspace';
  const safeBaseName = WINDOWS_RESERVED_NAMES.has(sanitized.toUpperCase())
    ? `${sanitized}_workspace`
    : sanitized;
  return `${safeBaseName}.feap`;
}

function sanitizeFileName(value) {
  return value
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')
    .replace(/[.\s]+$/g, '')
    .trim();
}

function normalizeRelativePath(value) {
  return String(value).replace(/\\/g, '/');
}

function toolResult(payload) {
  return {
    content: [
      {
        type: 'text',
        text: JSON.stringify(payload, null, 2),
      },
    ],
    isError: payload.status === 'failed',
  };
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

async function handleRequest(request) {
  const { id, method, params } = request;

  if (method === 'initialize') {
    return {
      jsonrpc: '2.0',
      id,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: {
          name: 'argo',
          version: '1.0.0',
        },
      },
    };
  }

  if (method === 'notifications/initialized') {
    return null;
  }

  if (method === 'tools/list') {
    return {
      jsonrpc: '2.0',
      id,
      result: { tools: TOOLS },
    };
  }

  if (method === 'tools/call') {
    try {
      const result = await callTool(params.name, params.arguments || {});
      return { jsonrpc: '2.0', id, result };
    } catch (error) {
      return {
        jsonrpc: '2.0',
        id,
        result: {
          content: [
            {
              type: 'text',
              text: String(error && error.stack ? error.stack : error),
            },
          ],
          isError: true,
        },
      };
    }
  }

  if (method === 'ping') {
    return { jsonrpc: '2.0', id, result: {} };
  }

  return {
    jsonrpc: '2.0',
    id,
    error: {
      code: -32601,
      message: `Method not found: ${method}`,
    },
  };
}

async function main() {
  const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });

  for await (const line of rl) {
    if (!line.trim()) {
      continue;
    }
    let request;
    try {
      request = JSON.parse(line);
    } catch {
      continue;
    }
    const response = await handleRequest(request);
    if (response) {
      send(response);
    }
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = {
  callTool,
  main,
};
