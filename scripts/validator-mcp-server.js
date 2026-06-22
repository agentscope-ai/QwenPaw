const { execFile } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);

const HANDOFF_STAGES = ['intent-to-implementation', 'implementation-to-coding'];
const DEFAULT_TRACE_PROPOSAL_PATH = 'design/KG/ImplementationToIntentTraceProposal.json';
const DEFAULT_ARCHITECTURE_GRAPH_PATH = 'design/KG/SystemArchitecture.json';

const SCRIPT_CANDIDATES = {
  validateSystemArchitecture: [
    'scripts/validateSystemArchitecture.js',
  ],
  validateStageHandoff: [
    'scripts/validateStageHandoff.js',
  ],
  validateTraceProposal: [
    'scripts/validateTraceProposal.js',
  ],
  runArchitectureTests: [
    'scripts/runArchitectureTests.js',
  ],
};

const TOOLS = [
  {
    name: 'validateSystemArchitecture',
    description: 'Validate design/KG/SystemArchitecture.json against schema/SystemArchitecture.schema.json and Argo graph rules.',
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
          enum: HANDOFF_STAGES,
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
          description: `Optional proposal path relative to workspace root. Default: ${DEFAULT_TRACE_PROPOSAL_PATH}`,
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
          description: `Optional architecture graph path relative to workspace root. Default: ${DEFAULT_ARCHITECTURE_GRAPH_PATH}`,
        },
      },
      additionalProperties: false,
    },
  },
];

function resolveWorkspaceRoot() {
  return process.env.ARGO_REPO_ROOT
    || process.env.WORKSPACE_FOLDER
    || path.resolve(__dirname, '..');
}

function resolveScriptPath(workspaceRoot, candidates) {
  for (const relativePath of candidates) {
    const absolutePath = path.join(workspaceRoot, relativePath);
    if (fs.existsSync(absolutePath)) {
      return { absolutePath, relativePath };
    }
  }

  throw new Error(`Unable to locate validator script. Checked: ${candidates.join(', ')}`);
}

async function runValidatorScript(workspaceRoot, scriptKey, args = []) {
  const { absolutePath, relativePath } = resolveScriptPath(workspaceRoot, SCRIPT_CANDIDATES[scriptKey]);
  const command = process.execPath;
  const commandArgs = [absolutePath, ...args];

  try {
    const { stdout, stderr } = await execFileAsync(command, commandArgs, {
      cwd: workspaceRoot,
      env: {
        ...process.env,
        ARGO_REPO_ROOT: workspaceRoot,
      },
      maxBuffer: 10 * 1024 * 1024,
    });

    return {
      status: 'passed',
      exitCode: 0,
      workspaceRoot,
      scriptPath: relativePath,
      command: [command, ...commandArgs],
      stdout: stdout.trim(),
      stderr: stderr.trim(),
    };
  } catch (error) {
    return {
      status: 'failed',
      exitCode: typeof error.code === 'number' ? error.code : 1,
      workspaceRoot,
      scriptPath: relativePath,
      command: [command, ...commandArgs],
      stdout: String(error.stdout || '').trim(),
      stderr: String(error.stderr || error.message || error).trim(),
    };
  }
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
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

async function callTool(name, args) {
  const workspaceRoot = resolveWorkspaceRoot();

  if (name === 'validateSystemArchitecture') {
    return toolResult(await runValidatorScript(workspaceRoot, 'validateSystemArchitecture'));
  }

  if (name === 'validateStageHandoff') {
    const stage = args && args.stage;
    if (stage && !HANDOFF_STAGES.includes(stage)) {
      throw new Error(`Unsupported handoff stage '${stage}'. Expected one of: ${HANDOFF_STAGES.join(', ')}`);
    }
    return toolResult(await runValidatorScript(workspaceRoot, 'validateStageHandoff', stage ? [stage] : []));
  }

  if (name === 'validateTraceProposal') {
    const proposalPath = (args && args.proposalPath) || DEFAULT_TRACE_PROPOSAL_PATH;
    return toolResult(await runValidatorScript(workspaceRoot, 'validateTraceProposal', [proposalPath]));
  }

  if (name === 'runArchitectureTests') {
    const architecturePath = (args && args.architecturePath) || DEFAULT_ARCHITECTURE_GRAPH_PATH;
    return toolResult(await runValidatorScript(workspaceRoot, 'runArchitectureTests', [architecturePath]));
  }

  throw new Error(`Unknown tool: ${name}`);
}

async function handleRequest(request) {
  const { id, method, params } = request;

  if (method === 'initialize') {
    return {
      jsonrpc: '2.0',
      id,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: {
          tools: {},
        },
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
      result: {
        tools: TOOLS,
      },
    };
  }

  if (method === 'tools/call') {
    try {
      const result = await callTool(params.name, params.arguments || {});
      return {
        jsonrpc: '2.0',
        id,
        result,
      };
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
    return {
      jsonrpc: '2.0',
      id,
      result: {},
    };
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
