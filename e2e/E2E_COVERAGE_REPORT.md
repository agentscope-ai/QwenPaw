# E2E 自动化覆盖报告

## 覆盖统计

- **总用例数**：172 个
- **P0（核心功能）**：67 个
- **P1（重要功能）**：72 个
- **P2（边界场景）**：35 个
- **测试文件数**：23 个
- **覆盖模块数**：23 个
- **最近全量执行**：2026-04-27 | 待执行

---

## 模块用例明细

| 模块 | 测试文件 | P0 | P1 | P2 | 合计 |
|------|---------|----|----|----|----|
| Chat | test_chat.py | 4 | 4 | 3 | 11 |
| 智能体(Agents) | test_agents.py | 6 | 2 | 4 | 12 |
| 频道(Channels) | test_channels.py | 3 | 5 | 2 | 10 |
| 定时任务(CronJobs) | test_cronjobs.py | 2 | 2 | 4 | 8 |
| 跨模块集成(CrossModule) | test_cross_module.py | 0 | 5 | 0 | 5 |
| Debug日志 | test_debug.py | 2 | 3 | 0 | 5 |
| 环境变量(Environments) | test_environments.py | 4 | 5 | 3 | 12 |
| 文件管理(Files) | test_files.py | 4 | 2 | 2 | 8 |
| 心跳(Heartbeat) | test_heartbeat.py | 2 | 0 | 2 | 4 |
| 认证登录(Login) | test_login.py | 2 | 3 | 0 | 5 |
| MCP客户端 | test_mcp.py | 3 | 2 | 0 | 5 |
| 本地模型(Models) | test_models.py | 4 | 4 | 2 | 10 |
| 运行配置(RuntimeConfig) | test_runtime_config.py | 3 | 6 | 1 | 10 |
| 安全防护(Security) | test_security.py | 3 | 4 | 1 | 8 |
| 会话管理(Sessions) | test_sessions.py | 3 | 2 | 0 | 5 |
| 技能池(SkillPool) | test_skill_pool.py | 1 | 5 | 1 | 7 |
| 技能管理(Skills) | test_skills.py | 3 | 5 | 0 | 8 |
| Token消耗(TokenUsage) | test_token_usage.py | 1 | 3 | 1 | 5 |
| 内置工具(Tools) | test_tools.py | 2 | 0 | 2 | 4 |
| 语音转写(Voice) | test_voice.py | 3 | 0 | 1 | 4 |
| 备份管理(Backups) | test_backups.py | 4 | 4 | 2 | 10 |
| 智能体统计(AgentStats) | test_agent_stats.py | 3 | 3 | 2 | 8 |
| ACP配置(ACP) | test_acp.py | 3 | 3 | 2 | 8 |
| **合计** | | **67** | **72** | **35** | **172** |

---

## 各模块用例清单

### Chat（test_chat.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestNewChatAndBasicQA | test_new_chat_basic_qa_copy | P0 | 新建对话+基础问答+消息复制 |
| TestMultiTurnConversation | test_multi_turn_context_awareness | P0 | 多轮对话+上下文记忆 |
| TestFileUploadAndQA | test_upload_file_and_ask_questions | P0 | 附件上传+基于文件问答 |
| TestSessionManagement | test_session_rename_pin_delete_switch | P0 | 会话管理完整流程 |
| TestAdvancedFeatures | test_model_switch_and_skill_invocation | P1 | 模型切换+技能调用 |
| TestChatMessageSearch | test_chat_message_search | P1 | 聊天消息搜索 |
| TestChatMessageEdit | test_chat_message_edit | P1 | 消息编辑/重新生成 |
| TestChatStopGeneration | test_chat_stop_generation | P1 | 流式输出中断/停止生成 |
| TestInputValidationAndEdgeCases | test_input_validation_and_special_chars | P2 | 输入验证+特殊字符 |
| TestChatLongMessage | test_chat_long_message | P2 | 超长消息输入 |
| TestChatIMEInput | test_chat_ime_input | P2 | IME 输入法组合事件处理 |

### 智能体（test_agents.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestAgentList | test_agent_list_display_and_refresh | P0 | 列表展示与刷新 |
| TestCreateAgent | test_create_agent_success | P0 | 创建智能体 |
| TestCreateAgent | test_create_agent_cancel | P0 | 取消创建 |
| TestCreateAgent | test_create_agent_name_required | P0 | 名称必填验证 |
| TestEditAgent | test_edit_agent_info | P0 | 编辑智能体信息 |
| TestToggleAgent | test_toggle_agent_status | P0 | 启用/禁用智能体 |
| TestAgentAPI | test_agent_api_operations | P1 | API 操作验证 |
| TestAgentDragReorder | test_agent_drag_reorder | P1 | 拖拽排序 |
| TestDeleteAgent | test_delete_agent_success | P2 | 删除智能体 |
| TestDeleteAgent | test_delete_agent_cancel | P2 | 取消删除 |
| TestAgentProtection | test_default_agent_protected | P2 | 默认智能体保护 |
| TestAgentSkillAssociation | test_agent_skill_association | P2 | 智能体技能关联配置 |

### 频道（test_channels.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestChannelListAndFilter | test_channel_list_filter_and_type | P0 | 列表展示+过滤+类型识别 |
| TestEditAndCancelChannelConfig | test_edit_save_then_cancel | P0 | 编辑配置+保存和取消 |
| TestEnableDisableChannel | test_toggle_channel_status | P0 | 启用/禁用频道 |
| TestFilterEditEnableCombo | test_filter_edit_and_toggle | P1 | 过滤+编辑+启用组合操作 |
| TestChannelMessageFilterConfig | test_channel_message_filter_config | P1 | 消息过滤配置 |
| TestChannelAccessControlPolicy | test_channel_access_control_policy | P1 | 访问控制策略 |
| TestCustomChannelConfig | test_custom_channel_config | P1 | 自定义频道添加与配置 |
| TestChannelQrCode | test_channel_qr_code | P1 | 二维码生成功能 |
| TestChannelConfigForms | test_dingtalk_and_feishu_config_forms | P2 | 钉钉/飞书表单验证 |
| TestChannelBotPrefix | test_channel_bot_prefix | P2 | Bot 前缀配置验证 |

### 定时任务（test_cronjobs.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestCronJobLifecycle | test_cronjob_lifecycle | P0 | 生命周期（创建/编辑/删除） |
| TestCronJobToggleAndExecute | test_toggle_and_execute | P0 | 启用/禁用+立即执行 |
| TestCronjobScheduleTypeSwitch | test_cronjob_schedule_type_switch | P1 | 调度类型切换 |
| TestCronjobEditAndUpdate | test_cronjob_edit_and_update | P1 | 定时任务编辑与更新 |
| TestCronJobScheduleAndTaskType | test_schedule_type_and_task_type | P2 | 调度类型与任务类型 |
| TestCronjobWeeklySchedule | test_cronjob_weekly_schedule | P2 | Weekly 调度+星期多选 |
| TestCronjobJsonParams | test_cronjob_json_params | P2 | JSON 请求参数输入验证 |
| TestCronjobTimezone | test_cronjob_timezone | P2 | 时区选择与切换 |

### 跨模块集成（test_cross_module.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestSkillAgentChatFlow | test_skill_to_agent_to_chat | P1 | 技能→智能体→Chat 端到端流程 |
| TestModelSwitchInChat | test_model_switch_and_chat_continuity | P1 | 模型切换后对话连续性 |
| TestSecurityInterceptionInChat | test_security_config_affects_chat | P1 | 安全配置与 Chat 行为联动 |
| TestWorkspaceFileChatFlow | test_workspace_file_and_chat_qa | P1 | 工作区文件与 Chat 问答联动 |
| TestEnvAndRuntimeConfigFlow | test_env_and_runtime_config_consistency | P1 | 环境变量与运行时配置一致性 |

### 环境变量（test_environments.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestEnvironmentListDisplay | test_environment_list_display | P0 | 页面加载+列表展示 |
| TestAddEnvironment | test_add_environment_success | P0 | 成功添加环境变量 |
| TestEditEnvironment | test_edit_environment | P0 | 编辑环境变量 |
| TestDeleteEnvironment | test_delete_environment | P0 | 删除环境变量 |
| TestEnvVarMultiRowAndCheckbox | test_env_var_multi_row_and_checkbox | P1 | 多行添加+checkbox |
| TestEnvVarSaveAndPersist | test_env_var_save_and_persist | P1 | 保存持久化验证 |
| TestBatchOperations | test_batch_operations | P1 | 批量操作 |
| TestEnvironmentAPI | test_environment_api | P1 | API 操作验证 |
| TestEnvKeyDuplicateDetection | test_env_key_duplicate_detection | P1 | Key 重复冲突检测 |
| TestAddEnvironment | test_add_environment_cancel | P2 | 取消添加 |
| TestAddEnvironment | test_add_environment_key_required | P2 | Key 必填验证 |
| TestEnvVarKeyValidation | test_env_var_key_format_validation | P2 | Key 格式校验 |

### 文件管理（test_files.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestFileListEditSave | test_file_list_view_edit_save | P0 | 页面加载+文件列表+编辑器 |
| TestFileToggleReorderMemory | test_file_toggle_reorder_memory | P0 | 开关切换+拖拽排序 |
| TestFileContentEditAndSave | test_file_content_edit_save_reset | P0 | 文件内容编辑保存与重置 |
| TestWorkspaceUploadDownload | test_workspace_download_and_upload_button | P0 | 工作空间上传下载 |
| TestDailyMemoryView | test_daily_memory_view | P1 | 每日记忆展开/折叠查看 |
| TestMarkdownPreview | test_markdown_preview | P1 | Markdown 实时预览 |
| TestWorkspaceZipUpload | test_workspace_zip_upload | P2 | ZIP 上传恢复工作区 |
| TestWorkspaceZipDownload | test_workspace_zip_download | P2 | ZIP 下载工作区 |

### 心跳（test_heartbeat.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestHeartbeatDisplayAndToggle | test_heartbeat_display_and_toggle | P0 | 页面展示+启用/禁用 |
| TestHeartbeatFullConfig | test_full_heartbeat_configuration | P0 | 完整配置流程 |
| TestHeartbeatTargetAndActiveHours | test_target_session_and_active_hours | P2 | 目标会话与活跃时间段 |
| TestHeartbeatIntervalUnit | test_heartbeat_interval_unit | P2 | 间隔单位切换（分钟/小时组合） |

### 认证登录（test_login.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestAuthStatus | test_auth_status_api | P0 | 认证状态 API |
| TestLoginPageAccess | test_login_page_accessible | P0 | 登录页面可访问性 |
| TestMultiUserManagement | test_multi_user_management | P1 | 多用户管理/权限控制 |
| TestLoginFormValidation | test_login_empty_form_validation | P1 | 登录空表单校验 |
| TestLoginFormValidation | test_login_partial_form_validation | P1 | 登录部分表单校验 |

### MCP客户端（test_mcp.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestMCPListAndOperations | test_mcp_list_toggle_and_cancel_delete | P0 | 列表+启用/禁用+取消删除 |
| TestCreateMCPClient | test_create_mcp_client_stdio_and_http | P0 | 创建对话框+JSON填写 |
| TestMCPClientCreateAndDelete | test_create_and_delete_mcp_client | P0 | 创建并删除MCP客户端 |
| TestMcpClientEdit | test_mcp_client_edit | P1 | MCP 客户端编辑配置 |
| TestMcpMultiProtocol | test_mcp_multi_protocol | P1 | 多协议创建（stdio/sse/streamable-http） |

### 本地模型（test_models.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestModelListDisplay | test_model_list_display | P0 | 页面加载+模型列表 |
| TestModelDownload | test_model_download_flow | P0 | 模型下载流程 |
| TestModelServe | test_model_serve_flow | P0 | 模型启动服务 |
| TestModelManagement | test_model_management_operations | P0 | 模型管理操作 |
| TestCustomProviderCreateAndDelete | test_custom_provider_create_and_delete | P1 | 自定义 Provider 创建删除 |
| TestProviderConfigAndConnection | test_provider_config_and_connection_test | P1 | Provider 配置与连接测试 |
| TestProviderSearchFilter | test_provider_search_filter | P1 | Provider 搜索过滤 |
| TestModelActivation | test_model_activation | P1 | 模型激活与切换 |
| TestOpenRouterFilter | test_openrouter_filter | P2 | OpenRouter 过滤配置 |
| TestModelJsonEditor | test_model_json_editor | P2 | JSON 配置编辑器 |

### 运行配置（test_runtime_config.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestReActAgentConfig | test_react_agent_language_and_timezone | P0 | ReAct 智能体语言+时区 |
| TestAgentConfigTabSwitch | test_agent_config_tab_switch | P0 | Tab 切换验证 |
| TestAgentConfigSaveAndReset | test_config_save_and_reset | P0 | 配置保存与重置 |
| TestLlmRetryConfig | test_llm_retry_config | P1 | LLM 重试配置 |
| TestLlmRateLimiterConfig | test_llm_rate_limiter_config | P1 | LLM 并发限流配置 |
| TestToolResultCompactConfig | test_tool_result_compact_config | P1 | 工具结果压缩配置 |
| TestEmbeddingConfig | test_embedding_config | P1 | Embedding 配置 |
| TestContextCompactConfig | test_context_compact_config | P1 | 上下文压缩配置 |
| TestMemorySummaryConfig | test_memory_summary_config | P1 | 记忆摘要配置 |
| TestConfigDynamicLinkage | test_config_dynamic_linkage | P2 | 配置项动态联动验证 |

### 安全防护（test_security.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestSecurityToolGuardAndTabSwitch | test_tool_guard_toggle_and_tab_switch | P0 | 工具防护+Tab 切换 |
| TestSecurityFileGuardPathAndToolSelect | test_file_guard_path_add_and_tool_select | P0 | 文件防护路径+工具选择 |
| TestSecurityConfigSaveAndPersist | test_security_config_save_and_persist | P0 | 配置保存与持久化 |
| TestSecurityRuleCrud | test_security_rule_crud | P1 | 安全规则 CRUD |
| TestSkillScannerModeSwitch | test_skill_scanner_mode_switch | P1 | 技能扫描模式切换 |
| TestDeniedToolsConfig | test_denied_tools_config | P1 | 拒绝工具列表配置 |
| TestRulePreview | test_rule_preview | P1 | 规则预览与匹配验证 |
| TestSecurityBatchRuleToggle | test_security_batch_rule_toggle | P2 | 批量启用/禁用规则 |

### 会话管理（test_sessions.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestSessionListFilterAndDetail | test_session_list_filter_and_detail | P0 | 列表展示+过滤+详情 |
| TestEditAndDeleteSession | test_edit_and_delete_session | P0 | 编辑与删除 |
| TestSessionEditAndSave | test_session_edit_name_and_save | P0 | 名称编辑保存 |
| TestSessionBatchDelete | test_session_batch_delete | P1 | 批量删除 |
| TestSessionFilterByUseridAndChannel | test_session_filter_by_userid_and_channel | P1 | 按用户/频道过滤 |

### 技能池（test_skill_pool.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestSkillPoolPageLoad | test_skill_pool_page_load | P0 | 技能池页面加载 |
| TestSkillPoolSearch | test_skill_pool_search | P1 | 技能池搜索/筛选 |
| TestSkillPoolInstall | test_skill_pool_install | P1 | 技能安装到智能体 |
| TestSkillPoolBroadcast | test_skill_pool_broadcast | P1 | 技能广播到多个智能体 |
| TestSkillPoolBatchDelete | test_skill_pool_batch_delete | P1 | 批量删除技能 |
| TestSkillPoolZipImport | test_skill_pool_zip_import | P1 | ZIP 导入技能 |
| TestSkillPoolBuiltinImport | test_skill_pool_builtin_import | P2 | 导入内置技能包 |

### 技能管理（test_skills.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestSkillListAndFilter | test_skill_list_filter_and_search | P0 | 列表展示+搜索筛选 |
| TestSkillImportToggleDeleteBatch | test_import_toggle_delete_and_batch | P0 | 启用/禁用+批量操作 |
| TestSkillCRUDLifecycle | test_skill_create_edit_delete | P0 | 技能 CRUD 完整流程 |
| TestSkillTagManagementAndFilter | test_skill_tag_management_and_filter | P1 | 标签管理与过滤 |
| TestSkillViewToggle | test_skill_view_toggle | P1 | 视图切换（卡片/列表） |
| TestSkillImportFromHub | test_skill_import_from_hub | P1 | 从 Hub 导入技能 |
| TestSkillPoolSync | test_skill_pool_sync | P1 | 技能池上传/下载同步 |
| TestSkillUploadZip | test_skill_upload_via_zip | P1 | ZIP 文件上传技能 |

### Token消耗（test_token_usage.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestTokenUsageDisplay | test_token_usage_overview | P0 | Token 消耗概览展示 |
| TestTokenUsageByModel | test_token_usage_by_model | P1 | 按模型统计 Token 消耗 |
| TestTokenUsageByDate | test_token_usage_by_date | P1 | 按日期统计 Token 趋势 |
| TestTokenUsageDateFilter | test_token_usage_date_filter | P1 | 时间范围筛选 |
| TestTokenUsageEmptyState | test_token_usage_empty_state | P2 | 空数据/加载状态展示 |

### 内置工具（test_tools.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestToolsPageDisplayAndGlobalToggle | test_tools_page_display_and_global_toggle | P0 | 页面展示+全局开关 |
| TestToolEnableDisableAndAsyncToggle | test_tool_enable_disable_and_async_toggle | P0 | 单个工具启用/禁用 |
| TestToolsGlobalToggleConsistency | test_global_toggle_consistency | P2 | 全局开关一致性 |
| TestToolAsyncSwitch | test_tool_async_switch | P2 | 异步执行开关验证 |

### 语音转写（test_voice.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestVoiceConfigDisplay | test_voice_config_display | P0 | 语音配置展示 |
| TestVoiceToggle | test_voice_service_toggle | P0 | 语音服务启用/禁用 |
| TestVoiceServiceConfig | test_twilio_config_form | P0 | Twilio 配置表单 |
| TestVoiceModeSwitch | test_voice_mode_switch | P2 | 音频模式切换（auto/native） |

### Debug日志（test_debug.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestDebugPageDisplay | test_debug_page_load_and_display | P0 | Debug 页面加载和展示 |
| TestDebugLogControls | test_debug_log_control_buttons | P0 | 日志控制按钮 |
| TestDebugLogLevelFilter | test_debug_log_level_filter | P1 | 日志级别过滤 |
| TestDebugLogSearch | test_debug_log_keyword_search | P1 | 日志关键词搜索 |
| TestDebugLogFileInfo | test_debug_log_file_info | P1 | 日志文件信息展示 |

### 备份管理（test_backups.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestBackupPageDisplay | test_backup_page_load_and_display | P0 | 页面加载+列表展示+操作按钮 |
| TestCreateBackupModalAndCancel | test_create_backup_modal_and_cancel | P0 | 创建备份模态框+取消操作 |
| TestCreateFullBackup | test_create_full_backup | P0 | 全量备份创建流程 |
| TestImportBackupEntry | test_import_backup_entry | P0 | 导入备份按钮与文件上传入口 |
| TestBackupSearchAndFilter | test_backup_search_and_filter | P1 | 备份搜索与过滤 |
| TestBackupRestoreModal | test_backup_restore_modal | P1 | 恢复模态框+恢复模式+预快照 |
| TestBackupDeleteAndCancel | test_backup_delete_and_cancel | P1 | 删除与取消删除 |
| TestBackupExport | test_backup_export | P1 | 导出功能验证 |
| TestCreatePartialBackup | test_create_partial_backup_options | P2 | 部分备份（Agent 选择） |
| TestBackupListRefreshAndEmpty | test_backup_list_refresh_and_empty | P2 | 列表刷新与空状态 |

### 智能体统计（test_agent_stats.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestAgentStatsPageDisplay | test_agent_stats_page_load_and_cards | P0 | 页面加载+汇总卡片展示 |
| TestAgentStatsDatePicker | test_date_range_picker_interaction | P0 | 日期范围筛选器交互 |
| TestAgentStatsCharts | test_chart_area_display | P0 | 趋势图表区域展示 |
| TestAgentStatsChannelDistribution | test_channel_distribution_display | P1 | 渠道分布饼图展示 |
| TestAgentStatsDateFilter | test_date_filter_refreshes_data | P1 | 日期筛选后数据刷新 |
| TestAgentStatsCardTooltip | test_card_tooltip_display | P1 | 汇总卡片 Tooltip 提示 |
| TestAgentStatsEmptyAndLoading | test_empty_and_loading_states | P2 | 空状态与加载状态 |
| TestAgentStatsRefresh | test_page_refresh_data_persistence | P2 | 页面刷新后数据保持 |

### ACP配置（test_acp.py）
| 测试类 | 测试方法 | 优先级 | 覆盖功能 |
|--------|---------|--------|---------|
| TestACPPageDisplay | test_acp_page_load_and_card_list | P0 | 页面加载+卡片列表+内置ACP |
| TestCreateACPDrawerForm | test_create_acp_drawer_form | P0 | 创建抽屉表单字段验证 |
| TestACPToggleSwitch | test_acp_toggle_switch | P0 | 启用/禁用切换+恢复 |
| TestACPFilterTabs | test_filter_tabs_switch | P1 | 过滤标签切换(All/Builtin/Custom) |
| TestEditACPConfig | test_edit_acp_config | P1 | 编辑 ACP 配置 |
| TestCreateAndDeleteCustomACP | test_create_and_delete_custom_acp | P1 | 创建自定义 ACP 并删除 |
| TestBuiltinACPProtection | test_builtin_acp_protection | P2 | 内置 ACP 保护验证 |
| TestACPCardDetails | test_acp_card_content_details | P2 | ACP 卡片内容详情验证 |

---

## 测试执行结果

- **最近一次全量执行**：2026-04-27
- **总用例数**：172
- **通过**：待执行
- **失败**：待执行
- **跳过**：待执行
- **通过率**：待执行
