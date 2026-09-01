import assert from "node:assert/strict";
import test from "node:test";

import {
  deploymentStatusPresentation,
  isGitHubBindingError,
  parseCreatedDeploymentId,
  parsePlatformDeployment,
  parsePlatformDeploymentLogs,
  parsePlatformDeployments,
  platformDeploymentErrorMessage,
} from "./deploymentModel";

test("parses empty and populated Platform deployment lists", () => {
  assert.deepEqual(parsePlatformDeployments({ apps: [] }), []);
  assert.deepEqual(
    parsePlatformDeployments({ data: { apps: [{ appId: "paw-1" }] } }),
    [{ appId: "paw-1" }],
  );
  assert.deepEqual(
    parsePlatformDeployments({ data: { data: { list: [{ id: "paw-2" }] } } }),
    [{ appId: "paw-2" }],
  );
});

test("normalizes Platform deployment status and access URL", () => {
  assert.deepEqual(
    parsePlatformDeployment({
      status: "RUNNING",
      access_url: "https://paw.example.com/",
      version_type: "stable",
    }, "paw-1"),
    {
      appId: "paw-1",
      status: "running",
      accessUrl: "https://paw.example.com",
      errorMessage: undefined,
      message: undefined,
      progress: undefined,
      versionType: "stable",
    },
  );
  assert.equal(parseCreatedDeploymentId({ data: { appId: "paw-3" } }), "paw-3");
});

test("parses text and structured deployment logs", () => {
  assert.deepEqual(parsePlatformDeploymentLogs({ logs: [
    "Mounting files",
    { source: "qwenpaw", message: "Service ready" },
  ] }), ["Mounting files", "[QWENPAW] Service ready"]);
});

test("maps deployment status to native progress presentation", () => {
  assert.equal(deploymentStatusPresentation("idle").active, false);
  assert.equal(deploymentStatusPresentation("creating").active, true);
  assert.deepEqual(deploymentStatusPresentation("rate_limited"), {
    label: "部署进行中",
    detail: "Platform 正在处理请求，App 会自动重试，无需操作。",
    active: true,
    failed: false,
  });
  assert.equal(deploymentStatusPresentation("running").label, "QwenPaw 已就绪");
  assert.equal(deploymentStatusPresentation("restarting").active, true);
  assert.equal(deploymentStatusPresentation("failed").failed, true);
});

test("provides actionable Platform deployment errors", () => {
  const error = new Error("ASP.AUTH.GITHUB_BIND_REQUIRED");
  assert.equal(isGitHubBindingError(error), true);
  assert.match(platformDeploymentErrorMessage(error), /绑定 GitHub/);
  assert.match(
    platformDeploymentErrorMessage(new Error("QWENPAW_QUALIFICATION_DENIED")),
    /部署资格/,
  );
  assert.match(
    platformDeploymentErrorMessage(new Error(
      "Error while extracting response for application/octet-stream",
    )),
    /不会重复部署/,
  );
});

test("preserves Platform deployment progress and failure details", () => {
  assert.deepEqual(parsePlatformDeployment({
    appId: "paw-failed",
    status: "FAILED",
    progress: 100,
    message: "唤醒失败",
    errorMessage: "wake up failed",
  }, "fallback"), {
    appId: "paw-failed",
    status: "failed",
    accessUrl: "",
    errorMessage: "wake up failed",
    message: "唤醒失败",
    progress: 100,
    versionType: undefined,
  });
});
