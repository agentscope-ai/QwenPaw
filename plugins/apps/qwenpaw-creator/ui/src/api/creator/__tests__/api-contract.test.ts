import { describe, expect, it } from "vitest";
import { installMockFetch } from "@/test/mockFetch";
import {
  createAssetImport,
  createProject,
  decideFileProjectReview,
  patchProject,
  sendCreatorMessage,
  saveModelConfig,
  testModelConnection,
} from "@/api/creator";
import type { DocumentMetadata } from "@/contracts/creator/assets";

describe("new Creator API contract", () => {
  it("uses Project Patch and file Review routes with stable idempotency ids", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/runtime/reviews/review-1/decisions",
        response: {
          json: {
            review_id: "review-1",
            round_id: "round-1",
            request_id: "request-1",
            request_message_seq: 1,
            interrupted_run_id: "run-1",
            baseline_generation: 1,
            baseline_etag: "base",
            candidate_generation: 2,
            candidate_etag: "candidate",
            decision_token: "token-2",
            status: "RESOLVED",
            operations: [
              {
                kind: "update",
                json_pointer: "/name",
                file_id: null,
                target_ref: "project:p1",
                before_hash: "before",
                after_hash: "after",
                before: "P",
                after: "新名称",
                operation_id: "operation-1",
                ui_locator: { path: "/project/p1/plan" },
                decision: "ACCEPTED",
              },
            ],
            created_at: "now",
            updated_at: "now",
          },
        },
      },
      {
        match: "/projects/p1/project",
        method: "PATCH",
        response: {
          json: {
            projectId: "p1",
            generation: 2,
            etag: "etag-2",
            changedPointers: ["/name"],
            project: {},
          },
        },
      },
      {
        match: "/projects/p1/messages",
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 2,
            classification: "mutation_instruction",
            appendState: "appended",
            creatorSessionId: "s1",
            conversationId: "c1",
          },
        },
      },
      {
        match: "/projects",
        response: {
          json: {
            projectId: "p1",
            creatorSessionId: "s1",
            conversationId: "c1",
            projectSnapshotId: "snapshot-1",
            header: {},
          },
        },
      },
    ]);
    await createProject({
      clientRequestId: "project-key",
      name: "P",
      scenario: "general",
      aspectRatio: "16:9",
      resolution: "720P",
    });
    await sendCreatorMessage("p1", {
      clientMessageId: "message-key",
      conversationId: "c1",
      message: "目标",
    });
    await patchProject("p1", {
      clientCommandId: "patch-key",
      editSessionId: "edit-1",
      baseGeneration: 1,
      baseEtag: "etag-1",
      operations: [
        {
          op: "replace",
          path: "/name",
          value: "新名称",
          expectedValueHash: "sha256:old",
        },
      ],
    });
    await decideFileProjectReview("p1", "review-1", {
      decisionId: "decision-key",
      decisionToken: "token-1",
      decisions: [{ operation_id: "operation-1", decision: "ACCEPT" }],
    });
    expect(calls.map((call) => [call.method, call.url])).toEqual([
      ["POST", "/api/qwenpaw-creator/projects"],
      ["POST", "/api/qwenpaw-creator/projects/p1/messages"],
      ["PATCH", "/api/qwenpaw-creator/projects/p1/project"],
      [
        "POST",
        "/api/qwenpaw-creator/projects/p1/runtime/reviews/review-1/decisions",
      ],
    ]);
    expect(calls[0].headers["idempotency-key"]).toBe("project-key");
    expect(calls[1].headers["idempotency-key"]).toBe("message-key");
    expect(calls[2].headers["idempotency-key"]).toBe("patch-key");
    expect(calls[3].headers["idempotency-key"]).toBe("decision-key");
    expect(
      calls.every((call) =>
        call.url.startsWith("/api/qwenpaw-creator/projects"),
      ),
    ).toBe(true);
  });

  it("preserves browser folder paths and uses the canonical model probe", async () => {
    const { calls } = installMockFetch([
      {
        match: "/asset-imports",
        response: { json: { importId: "t1", taskId: "t1", eventSeq: 1 } },
      },
      { match: "/models/test", response: { json: { ok: true, ms: 12 } } },
    ]);
    const file = new File(["hello"], "story.txt", { type: "text/plain" });
    Object.defineProperty(file, "webkitRelativePath", {
      value: "sources/chapter/story.txt",
    });
    await createAssetImport("p1", [file], "ATTACH_SOURCE", "folder-key");
    await testModelConnection({
      type: "vlm",
      base_url: "https://example.test/v1",
      api_key: "secret",
      model_name: "qwen3.7-plus",
      protocol: "OpenAI 协议",
    });
    expect((calls[0].body as { files: File }).files.name).toBe(
      "sources/chapter/story.txt",
    );
    expect(
      (calls[0].body as { postIngestAction: string }).postIngestAction,
    ).toBe("ATTACH_SOURCE");
    expect(calls[0].headers["idempotency-key"]).toBe("folder-key");
    expect(calls[1]).toMatchObject({
      method: "POST",
      url: "/api/qwenpaw-creator/models/test",
      body: {
        type: "vlm",
        base_url: "https://example.test/v1",
        api_key: "secret",
        model_name: "qwen3.7-plus",
        protocol: "OpenAI 协议",
      },
    });
  });

  it("saves the complete single-file model configuration", async () => {
    const { calls } = installMockFetch([
      {
        match: "/models/config",
        method: "POST",
        response: { json: { ok: true } },
      },
    ]);
    await saveModelConfig({
      llm: {
        enabled: true,
        model_name: "configured-model",
        api_key: "new-secret",
        base_url: "https://example.test/v1",
        protocol: "OpenAI 协议",
        custom_protocol: "",
        multimodal: false,
      },
      vlm: {
        enabled: false,
        model_name: "",
        api_key: "",
        base_url: "",
        protocol: "OpenAI 协议",
        custom_protocol: "",
        use_llm: false,
        multimodal: false,
      },
      grounding: {
        enabled: true,
        model_name: "",
        api_key: "",
        base_url: "",
        protocol: "OpenAI 协议",
        custom_protocol: "",
        reuse_llm: true,
        validation_source: "llm",
        tavily_api_key: "",
        serper_api_key: "",
        native_search_enabled: true,
        search_provider: "dashscope_qwen",
        search_reuse_llm: true,
        search_model_name: "",
        search_api_key: "",
        search_base_url: "",
        search_protocol: "DashScope（百炼）",
      },
      asr: {
        enabled: false,
        model_name: "fun-asr",
        api_key: "",
        base_url: "https://dashscope.aliyuncs.com/api/v1",
        protocol: "DashScope Fun-ASR",
        custom_protocol: "",
        provider: "fun-asr",
        language: "",
        reuse_llm_key: true,
      },
      tts: {
        enabled: false,
        model_name: "qwen3-tts-flash",
        api_key: "",
        base_url: "https://dashscope.aliyuncs.com/api/v1",
        protocol: "DashScope（百炼）",
        custom_protocol: "",
        voice: "",
        reuse_llm_key: true,
        vc_model_name: "",
      },
      s2v: {
        enabled: false,
        model_name: "",
        api_key: "",
        base_url: "",
        protocol: "DashScope（百炼）",
        custom_protocol: "",
        detect_model_name: "",
        reuse_llm_key: true,
      },
      embedding: {
        enabled: false,
        model_name: "qwen3-vl-embedding",
        api_key: "",
        base_url: "https://dashscope.aliyuncs.com/api/v1",
        protocol: "DashScope（百炼）",
        custom_protocol: "",
        reuse_vlm_key: true,
      },
      image: {
        enabled: false,
        model_name: "",
        api_key: "",
        base_url: "",
        protocol: "OpenAI 协议",
        custom_protocol: "",
        translate_model: "",
        reuse_llm_key: true,
      },
      video: {
        enabled: false,
        model_name: "",
        api_key: "",
        base_url: "",
        protocol: "Volcano Engine（火山引擎）",
        custom_protocol: "",
        reuse_llm_key: true,
      },
      oss: {
        enabled: false,
        access_key_id: "LTAI-x",
        access_key_secret: "oss-secret",
        endpoint: "https://oss-cn-hangzhou.aliyuncs.com",
        bucket: "creator-store",
        public_base_url: "",
        policy_api_key: "",
      },
      executionAuthorization: { mode: "required" },
      creationCheckpoints: { mode: "required" },
      mediaReview: { mode: "required" },
      selfReview: {
        sync_enabled: false,
        media_enabled: false,
        render_enabled: false,
      },
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      url: "/api/qwenpaw-creator/models/config",
      body: {
        llm: { model_name: "configured-model", api_key: "new-secret" },
      },
    });
    expect(calls[0].headers["idempotency-key"]).toMatch(/^model-config-/);
    expect(
      (calls[0].body as { oss: Record<string, unknown> }).oss,
    ).toMatchObject({
      enabled: false,
      access_key_id: "LTAI-x",
      access_key_secret: "oss-secret",
      endpoint: "https://oss-cn-hangzhou.aliyuncs.com",
    });
  });

  it("mirrors the backend document metadata contract", () => {
    // schemas/assets.py DocumentMetadata serializes as camelCase pageCount.
    const document: DocumentMetadata = { format: "pdf", pageCount: 4 };
    expect(document).toEqual({ format: "pdf", pageCount: 4 });
    expect(Object.keys(document).sort()).toEqual(["format", "pageCount"]);
  });
});
