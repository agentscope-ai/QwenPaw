import fs from "node:fs";
import vm from "node:vm";
import { randomUUID } from "node:crypto";

const sourcePath = process.argv[2];
if (!sourcePath) {
  throw new Error("service worker source path is required");
}

const clone = (value) => JSON.parse(JSON.stringify(value));
const listener = { addListener() {} };

function createStorage() {
  const data = {};
  const counts = { set: 0, remove: 0 };
  return {
    data,
    counts,
    session: {
      async get(keys) {
        if (keys === null || keys === undefined) return clone(data);
        const requested = Array.isArray(keys) ? keys : [keys];
        return Object.fromEntries(
          requested
            .filter((key) => Object.hasOwn(data, key))
            .map((key) => [key, clone(data[key])]),
        );
      },
      async set(values) {
        counts.set += 1;
        Object.assign(data, clone(values));
      },
      async remove(keys) {
        counts.remove += 1;
        for (const key of (Array.isArray(keys) ? keys : [keys])) delete data[key];
      },
    },
  };
}

function createPort() {
  return {
    onMessage: listener,
    onDisconnect: listener,
    postMessage() {},
    disconnect() {},
  };
}

function createChrome(storage) {
  return {
    storage: { session: storage.session },
    debugger: {
      onEvent: listener,
      onDetach: listener,
    },
    webNavigation: {
      onCreatedNavigationTarget: listener,
      onCompleted: listener,
    },
    tabs: {
      onCreated: listener,
      onUpdated: listener,
      onActivated: listener,
      onRemoved: listener,
    },
    runtime: {
      onMessage: listener,
      onMessageExternal: listener,
      onInstalled: listener,
      onStartup: listener,
      lastError: null,
      connectNative() { return createPort(); },
      getManifest() { return { version: "test" }; },
      reload() {},
    },
    alarms: {
      onAlarm: listener,
      async get() { return { name: "qwenpaw-native-watchdog" }; },
      create() {},
    },
  };
}

function receiptKey(sessionId, commandId) {
  return `qwenpawCommandReceipt:${encodeURIComponent(sessionId)}:${encodeURIComponent(commandId)}`;
}

const storage = createStorage();
const sandbox = {
  chrome: createChrome(storage),
  crypto: { randomUUID },
  console: { log() {}, warn() {}, error() {} },
  setTimeout,
  clearTimeout,
  URL,
  TextEncoder,
  TextDecoder,
};
const source = fs.readFileSync(sourcePath, "utf8");
vm.runInNewContext(source, sandbox, { filename: sourcePath });

const commandParams = {
  sessionId: "session-1",
  commandId: "command-1",
  commandFingerprint: "fingerprint-1",
};

async function createCurrentReceipt(state = "COMPLETED") {
  const receipt = await sandbox.runReceiptCommand(commandParams, async () => ({ ok: true }));
  storage.data[receiptKey(commandParams.sessionId, commandParams.commandId)] = {
    ...receipt,
    state,
  };
  return storage.data[receiptKey(commandParams.sessionId, commandParams.commandId)];
}

function seedTargetReceipt(receipt) {
  storage.data[receiptKey(commandParams.sessionId, commandParams.commandId)] = receipt;
}

function statusParams() {
  return {
    sessionId: commandParams.sessionId,
    targetCommandId: commandParams.commandId,
    targetCommandFingerprint: commandParams.commandFingerprint,
  };
}

const scenarios = {
  async execute_order() {
    let stateWhenExecutorRan = null;
    const states = [];
    const originalSet = storage.session.set;
    storage.session.set = async (values) => {
      for (const value of Object.values(values)) {
        if (value && value.state) states.push(value.state);
      }
      await originalSet(values);
    };
    await sandbox.runReceiptCommand(commandParams, async () => {
      stateWhenExecutorRan = storage.data[
        receiptKey(commandParams.sessionId, commandParams.commandId)
      ].state;
      return { ok: true };
    });
    return { stateWhenExecutorRan, states };
  },

  async epoch_present() {
    const receipt = await sandbox.runReceiptCommand(commandParams, async () => ({ ok: true }));
    return { receipt };
  },

  async status_pure_read({ queries = 1 }) {
    seedTargetReceipt({ ...commandParams, state: "COMPLETED", result: null, updatedAt: Date.now() });
    storage.counts.set = 0;
    storage.counts.remove = 0;
    for (let index = 0; index < queries; index += 1) {
      await sandbox.queryCommandStatus(statusParams());
    }
    return {
      storageSetCalls: storage.counts.set,
      storageRemoveCalls: storage.counts.remove,
      targetReceiptStillPresent: Boolean(
        storage.data[receiptKey(commandParams.sessionId, commandParams.commandId)],
      ),
    };
  },

  async status_shape() {
    seedTargetReceipt({
      ...commandParams,
      state: "COMPLETED",
      executorEpoch: "extension-internal",
      result: null,
      updatedAt: Date.now(),
    });
    const params = statusParams();
    const response = await sandbox.queryCommandStatus(params);
    return {
      responseKeys: Object.keys(response),
      acceptedParams: Object.keys(params),
      targetReceipt: response.targetReceipt,
      targetCommandFact: response.targetCommandFact,
    };
  },

  async observed_states({ case: requestedCase }) {
    if (requestedCase === "evicted") {
      storage.data.qwenpawCommandReceiptEvictions = [{
        sessionId: commandParams.sessionId,
        commandId: commandParams.commandId,
        commandFingerprint: commandParams.commandFingerprint,
      }];
    } else if (requestedCase !== "absent") {
      const state = requestedCase.startsWith("received") ? "RECEIVED" :
        requestedCase.startsWith("running") ? "RUNNING" : "COMPLETED";
      const receipt = await createCurrentReceipt(state);
      if (requestedCase.endsWith("stale_epoch")) {
        receipt.executorEpoch = "stale-epoch";
      }
    }
    const response = await sandbox.queryCommandStatus(statusParams());
    return { observedState: response.targetCommandFact.observedState };
  },

  async stale_epoch_no_reexec() {
    seedTargetReceipt({
      ...commandParams,
      state: "RECEIVED",
      executorEpoch: "stale-epoch",
      result: null,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    });
    let executorCalls = 0;
    const receipt = await sandbox.runReceiptCommand(commandParams, async () => {
      executorCalls += 1;
      return { ok: true };
    });
    return { executorCalls, receiptState: receipt.state };
  },
};

const input = JSON.parse(await new Promise((resolve, reject) => {
  let body = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => { body += chunk; });
  process.stdin.on("end", () => resolve(body));
  process.stdin.on("error", reject);
}));
if (!Object.hasOwn(scenarios, input.scenario)) {
  throw new Error(`unknown scenario: ${input.scenario}`);
}
process.stdout.write(`${JSON.stringify(await scenarios[input.scenario](input))}\n`);
