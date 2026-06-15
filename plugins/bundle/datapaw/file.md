DataPaw Files Preview 404 排查说明

结论
/api/tasks/{session_id}/files 和 /api/tasks/{session_id}/files/preview 这组接口需要的 {session_id} 是后端真实会话 ID，例如：

11781330102407
当前前端请求里传的是 chat UUID：

13fc19fa0-81e7-4722-ab17-5851f6a4003f
即使请求已经带了 X-Agent-Id: datapaw，后端也不会自动把 chat UUID 转成真实 session ID。因此后端会去读不存在或为空的 DAG 文件，导致 /files 返回空数组，/files/preview 返回 404。

现象
前端 Files 面板中能看到文件，例如：

DAU 11-12月趋势图
12月DAU+WoW环比图
12月首访用户趋势图
DAU vs 首访对比图
12月DAU衍生指标CSV
观测摘要JSON
但点击 Preview 时请求失败：

1curl 'http://127.0.0.1:8088/api/tasks/3fc19fa0-81e7-4722-ab17-5851f6a4003f/files/preview?path=1781330102407%2Fgraph_6mjTtDsG%2Fn1_dau_observe%2Fdau_dec_wow.png&user_id=default' \
2  -H 'X-Agent-Id: datapaw'
返回 404，错误类似：

1{
2  "detail": "Artifact path '1781330102407/graph_6mjTtDsG/n1_dau_observe/dau_dec_wow.png' is not registered in this session."
3}
同样，用 chat UUID 调 /files 也返回空：

1curl -H 'X-Agent-Id: datapaw' \
2'http://127.0.0.1:8088/api/tasks/3fc19fa0-81e7-4722-ab17-5851f6a4003f/files?user_id=default&graph_id=graph_6mjTtDsG'
返回：

1{"files":[]}
关键证据
日志里有 chat UUID 到真实 session ID 的映射：

1Auto-registered new chat: 3fc19fa0-81e7-4722-ab17-5851f6a4003f -> 1781330102407
也就是说：

1chat id:    3fc19fa0-81e7-4722-ab17-5851f6a4003f
2session id: 1781330102407
后端真实 DAG 文件存在于：

1/Users/yolo/.qwenpaw/workspaces/datapaw/sessions/dag/default_1781330102407.json
该文件中：

1top-level artifacts: 17+
2n1_dau_observe output.files: 6
3n2_dau_anomaly output.files: 1
4n3_dau_drilldown output.files: 5
5n4_new_user_observe output.files: 5
使用真实 session ID 调用后端接口可以正常返回文件：

1curl -H 'X-Agent-Id: datapaw' \
2'http://127.0.0.1:8088/api/tasks/1781330102407/files?user_id=default&graph_id=graph_6mjTtDsG'
返回文件数量正常，例如：

1count=18
2DAU 11-12月趋势图 1781330102407/graph_6mjTtDsG/n1_dau_observe/dau_trend_nov_dec.png
预览接口也正常：

1curl -s -o /dev/null \
2  -w 'status=%{http_code}\ncontent_type=%{content_type}\nsize=%{size_download}\n' \
3  -H 'X-Agent-Id: datapaw' \
4  'http://127.0.0.1:8088/api/tasks/1781330102407/files/preview?path=1781330102407%2Fgraph_6mjTtDsG%2Fn1_dau_observe%2Fdau_trend_nov_dec.png&user_id=default'
返回：

1status=200
2content_type=image/png
3size=124222
后端行为说明
plugins/bundle/datapaw/core/routers/tasks.py 中，list_files 会直接使用 URL path 中传入的 session_id 去读 DAGStore：

1pn = await _load_pn_for_request(
2    session,
3    session_id,
4    user_id=user_id,
5)
DAGStore 的文件路径规则是：

1return self.sessions_root / "dag" / f"{safe_user}_{safe_sid}.json"
因此：

1/api/tasks/3fc19fa0-.../files
会读：

1sessions/dag/default_3fc19fa0-81e7-4722-ab17-5851f6a4003f.json
而真实数据在：

1sessions/dag/default_1781330102407.json
X-Agent-Id: datapaw 只负责选择 datapaw agent 的 session root，不负责把 chat UUID 转换成真实 session ID。

为什么前端 Files 面板能显示文件
前端节点抽屉的 Files Tab 不完全依赖 /api/tasks/{session_id}/files。

当前链路里，节点抽屉会拿 allFiles，而 allFiles 是由前端内存里的 currentPlan.nodes[*].output.files 和 taskArtifacts 合并得到的。

相关逻辑：

plugins/bundle/datapaw/frontend/src/pages/Chat/hooks/useTaskGraphChat.ts
plugins/bundle/datapaw/frontend/src/pages/Chat/components/TaskGraphPanel/fileUtils.ts
plugins/bundle/datapaw/frontend/src/pages/Chat/components/TaskGraphPanel/TaskNodeDrawer.tsx
所以会出现这种不一致：

1前端 Files Tab 能显示文件
2但 preview/download 请求使用了错误的 session id
3后端 artifacts 白名单按错误 session 查不到文件
4最终 404
前端修复建议
1. 调用 files/preview/download 前必须使用真实 session ID
在生成以下 URL 时：

1/api/tasks/{session_id}/files
2/api/tasks/{session_id}/files/preview
3/api/tasks/{session_id}/files/download
{session_id} 必须是 sessionApi.getRealIdForSession(chatId) 解析后的真实 session ID。

对当前 case，应该从：

13fc19fa0-81e7-4722-ab17-5851f6a4003f
解析为：

11781330102407
2. 不要使用 URL 中的 chat UUID 直接拼 task API
页面 URL 是：

1/chat/3fc19fa0-81e7-4722-ab17-5851f6a4003f
这里的 ID 是 chat id，不是 task API 需要的 session id。

3. preview_url/download_url 也要注意 session id 来源
后端 /files 返回的 preview_url 和 download_url 是用请求里的 session_id 构造的。

如果前端先用错误的 chat UUID 调 /files，即使后端返回了数据，URL 也可能继续携带错误 session id。正确做法是先用真实 session id 调 /files，或者前端生成 fallback URL 时显式使用真实 session id。

4. 保持 X-Agent-Id: datapaw
X-Agent-Id 仍然是需要的。它解决的是“读哪个 agent 的 session root”的问题；真实 session ID 解决的是“读这个 agent 下哪个 DAG 文件”的问题。

两个条件都要满足：

1X-Agent-Id = datapaw
2session_id = 1781330102407
验收方式
修复后，浏览器里 files 请求应类似：

1GET /api/tasks/1781330102407/files?user_id=default&graph_id=graph_6mjTtDsG
2X-Agent-Id: datapaw
预览请求应类似：

1GET /api/tasks/1781330102407/files/preview?path=1781330102407%2Fgraph_6mjTtDsG%2Fn1_dau_observe%2Fdau_dec_wow.png&user_id=default
2X-Agent-Id: datapaw
预期结果：

1/files 返回非空 files 数组
2/files/preview 返回 200 和对应文件 content-type