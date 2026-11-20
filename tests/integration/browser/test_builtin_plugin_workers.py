"""Exercise the installed worker entry points through the real browser host."""

import json
import base64
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import threading

import pytest


ROOT = Path(__file__).resolve().parents[3]
CONSOLE = ROOT / "console"

HOST_BUILD = """
const fs = require("fs");
const { build } = require("esbuild");
const outdir = process.argv[1];
const config = {bundle:true, jsx:"automatic", format:"esm", target:"es2022", logLevel:"silent", alias:{"@":process.cwd()+"/src"}};
Promise.all([
  build({...config, entryPoints:["src/plugins/isolated/plugin.worker.ts"], outfile:outdir + "/plugin.worker.ts"}),
  build({...config, stdin:{resolveDir:process.cwd(), contents:process.argv[2]},
    outfile:outdir + "/host.js", define:{VITE_API_BASE_URL:'""',TOKEN:'""',"import.meta.env":"{}"}})
]).catch(error => { console.error(error); process.exitCode = 1; });
"""

HOST_JS = """
import React from "react";
import { createRoot } from "react-dom/client";
import { PluginWorkerClient } from "./src/plugins/isolated/workerClient";
import { PluginView } from "./src/plugins/isolated/PluginView";
import { useAgentStore } from "./src/stores/agentStore";
import i18n from "i18next";
const root = createRoot(document.getElementById("plugin"));
useAgentStore.setState({selectedAgent:"agent-a"});
window.currentSessionId = "session-1";
window.setPluginLanguage = async (lng) => {i18n.language=lng; i18n.emit("languageChanged",lng);};
window.openPlugin = async (id, code, target, input) => {
  window.client?.stop();
  const client = window.client = new PluginWorkerClient(id, code);
  const items = await client.ready;
  root.render(React.createElement(PluginView, {client,target:target || items.find(i=>i.kind==="route").id, input:input || {}}));
  return items;
};
"""


class Static(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".ts": "text/javascript",
    }

    def log_message(self, *args):
        pass


@pytest.mark.e2e
def test_six_builtin_plugins_register_and_handle_actions(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    if not shutil.which("node") or not (CONSOLE / "node_modules/esbuild").exists():
        pytest.skip("Browser host build requires console dependencies")
    subprocess.run(
        ["node", "-e", HOST_BUILD, str(tmp_path), HOST_JS], cwd=CONSOLE, check=True
    )
    (tmp_path / "index.html").write_text(
        '<div id="plugin"></div><script type="module" src="/host.js"></script>',
        encoding="utf8",
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(Static, directory=str(tmp_path))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as driver:
            browser_path = os.environ.get("QWENPAW_TEST_CHROME_PATH")
            if not browser_path and not Path(driver.chromium.executable_path).exists():
                pytest.skip("Provide a local Chromium via QWENPAW_TEST_CHROME_PATH")
            browser = driver.chromium.launch(
                executable_path=browser_path, headless=True
            )
            try:
                _exercise(browser.new_page(locale="zh-CN"), server.server_port)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _exercise(page, port):
    calls = []
    issues, projects, messages = [], [], []
    state = {"enabled": False}
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGrsAAAAASUVORK5CYII="
    )
    project = {
        "name": "本地短剧",
        "description": "test",
        "timelines": {
            "items": {
                "cut": {
                    "timeline_id": "cut",
                    "elements_by_id": {
                        "intro": {
                            "element_id": "intro",
                            "label": "片头",
                            "span": {"start_tick": 0, "duration_tick": 60},
                        }
                    },
                },
            }
        },
    }
    review = {
        "review_id": "review1",
        "decision_token": "token1",
        "operations": [
            {
                "operation_id": "op1",
                "decision": "PENDING",
                "json_pointer": "/description",
                "before": "test",
                "after": "updated",
            },
        ],
    }

    def serve(route):
        from urllib.parse import urlparse

        req = route.request
        plugin, path = (
            urlparse(req.url)
            .path.removeprefix("/api/frontend_plugin/")
            .split("/runtime", 1)
        )
        assert req.headers["x-agent-id"] == "agent-a"
        body = (
            req.post_data_json or {}
            if "application/json" in req.headers.get("content-type", "")
            else {}
        )
        calls.append((plugin, req.method, path))
        result = {}
        if plugin == "agent-kanban" and path == "/issues":
            if req.method == "GET":
                result = {"issues": issues}
            else:
                result = {"id": "one", "status": "backlog", **body}
                issues.append(result)
        elif plugin == "qwenpaw-creator":
            if path.endswith("/assets") and req.method == "POST":
                assert b'name="file"; filename="frame.png"' in req.post_data_buffer
                project["assets"] = {
                    "source_versions_by_id": {
                        "v1": {
                            "name": "frame.png",
                            "version_id": "v1",
                            "media_type": "image/png",
                        }
                    }
                }
            elif path == "/media/assets/v1":
                route.fulfill(body=png, content_type="image/png")
                return
            elif path == "/projects" and req.method == "POST":
                result = {
                    "projectId": "project-one",
                    "conversationId": "story-room",
                    **body,
                }
                projects.append(result)
            elif path == "/projects":
                result = {"items": projects}
            elif path.endswith("/project"):
                if req.method == "PATCH":
                    import hashlib

                    op = body["operations"][0]
                    assert req.headers["idempotency-key"] == body["clientCommandId"]
                    assert body["baseEtag"] == "revision"
                    assert (
                        op["expectedValueHash"]
                        == "sha256:" + hashlib.sha256(b"60").hexdigest()
                    )
                    assert (
                        op["path"]
                        == "/timelines/items/cut/elements_by_id/intro/span/duration_tick"
                    )
                    project["timelines"]["items"]["cut"]["elements_by_id"]["intro"][
                        "span"
                    ]["duration_tick"] = op["value"]
                result = {"project": project, "generation": 1, "etag": "revision"}
            elif path.endswith("/reviews/active"):
                result = [review]
            elif path.endswith("/review1/decisions"):
                assert body["decisionToken"] == "token1"
                assert body["decisions"] == [
                    {"decision": "ACCEPT", "operation_id": "op1"}
                ]
                review["operations"][0]["decision"] = "ACCEPTED"
            elif path.endswith("/conversations"):
                result = {
                    "items": [{"conversationId": "story-room", "isDefault": True}]
                }
            elif path.endswith("/messages"):
                if req.method == "POST":
                    assert body["conversationId"] == "story-room"
                    messages.append(
                        {"role": "user", "content": [{"text": body["message"]}]}
                    )
                result = {"items": messages}
            elif path.endswith("/work-graph"):
                result = {
                    "nodes": [
                        {
                            "id": "story",
                            "label": "剧本",
                            "status": "待执行",
                            "dispatchable": True,
                        }
                    ]
                }
            elif path.endswith("/export"):
                import io
                import zipfile

                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as archive:
                    archive.writestr("project.json", '{"name":"local"}')
                route.fulfill(
                    body=buf.getvalue(), content_type="application/octet-stream"
                )
                return
        elif path == "/install-status":
            result = {"installed": True, "setup_phase": "ready"}
        elif path == "/open-chrome-extensions":
            result = {"opened": True}
        elif plugin == "computer-use":
            if path == "/feature":
                state.update(body)
            result = (
                {"access": []}
                if path == "/access"
                else {"runtime_available": True, **state}
            )
        elif path == "/pets":
            result = {"pets": [{"folder": "goose", "displayName": "小鹅"}]}
        elif path == "/status":
            result = {"desktop": {"running": True}}
        elif path == "/a2a/agents":
            result = {"agents": [{"alias": "剪辑", "status": "connected"}]}
        elif path == "/interaction/pending":
            result = {
                "id": "pending-1",
                "names": ["方案一"],
                "proposals": [[["主机", "测试资源"]]],
            }
        elif path == "/interaction":
            assert body == {
                "session_id": "session-1",
                "pending_id": "pending-1",
                "result": "用户选择了「方案一」并确认部署",
            }
        route.fulfill(json=result)

    page.route("**/api/frontend_plugin/**", serve)
    page.goto(f"http://127.0.0.1:{port}")
    page.wait_for_function("typeof window.openPlugin === 'function'")
    manifests = {}
    for manifest in (ROOT / "plugins").glob("*/*/plugin.json"):
        data = json.loads(manifest.read_text(encoding="utf8"))
        if data["entry"].get("frontend"):
            assert data["entry"]["frontend_runtime"] == "worker-v1"
            manifests[data["id"]] = (
                manifest.parent / data["entry"]["frontend"]
            ).read_text(encoding="utf8")
    assert len(manifests) == 6

    def open_plugin(plugin, target=None, props=None):
        return page.evaluate(
            "args => window.openPlugin(...args)",
            [plugin, manifests[plugin], target, props],
        )

    def click(text):
        page.get_by_role("button", name=text, exact=True).click()

    open_plugin("agent-kanban")
    page.get_by_label("标题", exact=True).fill("普通成员的看板")
    click("保存")
    page.get_by_role("button", name="普通成员的看板").wait_for()

    open_plugin("qwenpaw-creator")
    page.get_by_label("项目名称").fill("本地短剧")
    click("创建")
    page.get_by_role("button", name="本地短剧", exact=True).wait_for()
    page.get_by_label("创作或修改指令").fill("写三场戏")
    click("发送创作指令")
    page.get_by_text("user · 写三场戏").wait_for()
    page.get_by_text("剧本 · 待执行").wait_for()
    click("执行 剧本")
    page.get_by_text("制作任务已提交", exact=False).last.wait_for()
    assert (
        "qwenpaw-creator",
        "POST",
        "/projects/project-one/work-graph/nodes/story/dispatch",
    ) in calls
    click("片头 · 时长刻度 · 60")
    page.get_by_label("新值").fill("90")
    click("保存修改")
    page.get_by_role("button", name="片头 · 时长刻度 · 90").wait_for()
    click("接受变更")
    page.get_by_role("button", name="接受变更").wait_for(state="detached")
    page.get_by_label("导入项目素材").set_input_files(
        {"name": "frame.png", "mimeType": "image/png", "buffer": png}
    )
    click("预览素材")
    page.wait_for_function("document.querySelector('img')?.naturalWidth === 1")
    with page.expect_download() as download:
        click("导出项目 ZIP")
    import zipfile

    assert (
        zipfile.ZipFile(download.value.path()).read("project.json")
        == b'{"name":"local"}'
    )

    open_plugin("chrome")
    click("打开扩展管理")
    page.get_by_text("已打开", exact=True).wait_for()

    open_plugin("computer-use")
    click("启用桌面控制")
    page.get_by_role("button", name="停用桌面控制").wait_for()

    open_plugin("qwenpaw-pet")
    click("切换到 小鹅")
    page.get_by_text("已切换到 小鹅", exact=True).wait_for()

    items = open_plugin("cloudpaw")
    assert {i["tool"] for i in items if i["kind"] == "tool"} == {
        "proposal_choice",
        "manage_prd",
        "a2a_call",
    }
    page.get_by_text("剪辑 · connected").wait_for()
    open_plugin("cloudpaw", "proposal", {"data": {"id": "call-1", "content": []}})
    click("确认部署所选方案")
    page.get_by_text("用户选择了「方案一」并确认部署").wait_for()
    assert {plugin for plugin, _, _ in calls} == set(manifests)
    open_plugin("chrome")
    page.evaluate("window.setPluginLanguage('en')")
    page.get_by_role("button", name="Open extension manager").wait_for()
    page.evaluate("window.client.stop()")
    page.get_by_role("button", name="Open extension manager").wait_for(state="detached")
