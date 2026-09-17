# E2E Automation Coverage Report

## Coverage Summary

- **Total cases**: 172
- **P0 (core)**: 67
- **P1 (important)**: 72
- **P2 (edge)**: 35
- **Test files**: 23
- **Modules covered**: 23
- **Latest full run**: 2026-04-27 | pending

---

## Module Breakdown

| Module | Test file | P0 | P1 | P2 | Total |
|--------|-----------|----|----|----|----|
| Chat | test_chat.py | 4 | 4 | 3 | 11 |
| Agents | test_agents.py | 6 | 2 | 4 | 12 |
| Channels | test_channels.py | 3 | 5 | 2 | 10 |
| CronJobs | test_cronjobs.py | 2 | 2 | 4 | 8 |
| Cross-module Integration | test_cross_module.py | 0 | 5 | 0 | 5 |
| Debug Logs | test_debug.py | 2 | 3 | 0 | 5 |
| Environments | test_environments.py | 4 | 5 | 3 | 12 |
| Files | test_files.py | 4 | 2 | 2 | 8 |
| Heartbeat | test_heartbeat.py | 2 | 0 | 2 | 4 |
| Login | test_login.py | 2 | 3 | 0 | 5 |
| MCP Clients | test_mcp.py | 3 | 2 | 0 | 5 |
| Models | test_models.py | 4 | 4 | 2 | 10 |
| Runtime Config | test_runtime_config.py | 3 | 6 | 1 | 10 |
| Security | test_security.py | 3 | 4 | 1 | 8 |
| Sessions | test_sessions.py | 3 | 2 | 0 | 5 |
| Skill Pool | test_skill_pool.py | 1 | 5 | 1 | 7 |
| Skills | test_skills.py | 3 | 5 | 0 | 8 |
| Token Usage | test_token_usage.py | 1 | 3 | 1 | 5 |
| Tools | test_tools.py | 2 | 0 | 2 | 4 |
| Voice | test_voice.py | 3 | 0 | 1 | 4 |
| Backups | test_backups.py | 4 | 4 | 2 | 10 |
| Agent Stats | test_agent_stats.py | 3 | 3 | 2 | 8 |
| ACP | test_acp.py | 3 | 3 | 2 | 8 |
| **Total** | | **67** | **72** | **35** | **172** |

---

## Per-Module Case List

### Chat (test_chat.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestNewChatAndBasicQA | test_new_chat_basic_qa_copy | P0 | New chat + basic Q&A + message copy |
| TestMultiTurnConversation | test_multi_turn_context_awareness | P0 | Multi-turn dialogue + context memory |
| TestFileUploadAndQA | test_upload_file_and_ask_questions | P0 | Attachment upload + file-based Q&A |
| TestSessionManagement | test_session_rename_pin_delete_switch | P0 | End-to-end session management |
| TestAdvancedFeatures | test_model_switch_and_skill_invocation | P1 | Model switching + skill invocation |
| TestChatMessageSearch | test_chat_message_search | P1 | Chat message search |
| TestChatMessageEdit | test_chat_message_edit | P1 | Message edit / regenerate |
| TestChatStopGeneration | test_chat_stop_generation | P1 | Streaming output interrupt / stop generation |
| TestInputValidationAndEdgeCases | test_input_validation_and_special_chars | P2 | Input validation + special characters |
| TestChatLongMessage | test_chat_long_message | P2 | Extra-long message input |
| TestChatIMEInput | test_chat_ime_input | P2 | IME composition event handling |

### Agents (test_agents.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestAgentList | test_agent_list_display_and_refresh | P0 | List display and refresh |
| TestCreateAgent | test_create_agent_success | P0 | Create agent |
| TestCreateAgent | test_create_agent_cancel | P0 | Cancel creation |
| TestCreateAgent | test_create_agent_name_required | P0 | Name-required validation |
| TestEditAgent | test_edit_agent_info | P0 | Edit agent info |
| TestToggleAgent | test_toggle_agent_status | P0 | Enable/disable agent |
| TestAgentAPI | test_agent_api_operations | P1 | API operations |
| TestAgentDragReorder | test_agent_drag_reorder | P1 | Drag-and-drop reorder |
| TestDeleteAgent | test_delete_agent_success | P2 | Delete agent |
| TestDeleteAgent | test_delete_agent_cancel | P2 | Cancel deletion |
| TestAgentProtection | test_default_agent_protected | P2 | Default agent protection |
| TestAgentSkillAssociation | test_agent_skill_association | P2 | Agent-skill association config |

### Channels (test_channels.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestChannelListAndFilter | test_channel_list_filter_and_type | P0 | List + filter + type recognition |
| TestEditAndCancelChannelConfig | test_edit_save_then_cancel | P0 | Edit config + save and cancel |
| TestEnableDisableChannel | test_toggle_channel_status | P0 | Enable/disable channel |
| TestFilterEditEnableCombo | test_filter_edit_and_toggle | P1 | Filter + edit + enable combo |
| TestChannelMessageFilterConfig | test_channel_message_filter_config | P1 | Message filter config |
| TestChannelAccessControlPolicy | test_channel_access_control_policy | P1 | Access control policy |
| TestCustomChannelConfig | test_custom_channel_config | P1 | Add and configure custom channel |
| TestChannelQrCode | test_channel_qr_code | P1 | QR code generation |
| TestChannelConfigForms | test_dingtalk_and_feishu_config_forms | P2 | DingTalk / Feishu form validation |
| TestChannelBotPrefix | test_channel_bot_prefix | P2 | Bot prefix config validation |

### CronJobs (test_cronjobs.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestCronJobLifecycle | test_cronjob_lifecycle | P0 | Lifecycle (create/edit/delete) |
| TestCronJobToggleAndExecute | test_toggle_and_execute | P0 | Enable/disable + run now |
| TestCronjobScheduleTypeSwitch | test_cronjob_schedule_type_switch | P1 | Schedule type switching |
| TestCronjobEditAndUpdate | test_cronjob_edit_and_update | P1 | Cron job edit and update |
| TestCronJobScheduleAndTaskType | test_schedule_type_and_task_type | P2 | Schedule type and task type |
| TestCronjobWeeklySchedule | test_cronjob_weekly_schedule | P2 | Weekly schedule + multi-day selection |
| TestCronjobJsonParams | test_cronjob_json_params | P2 | JSON request parameter validation |
| TestCronjobTimezone | test_cronjob_timezone | P2 | Timezone selection and switching |

### Cross-module Integration (test_cross_module.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestSkillAgentChatFlow | test_skill_to_agent_to_chat | P1 | Skill -> Agent -> Chat end-to-end |
| TestModelSwitchInChat | test_model_switch_and_chat_continuity | P1 | Conversation continuity after model switch |
| TestSecurityInterceptionInChat | test_security_config_affects_chat | P1 | Security config affects Chat behavior |
| TestWorkspaceFileChatFlow | test_workspace_file_and_chat_qa | P1 | Workspace file and Chat Q&A integration |
| TestEnvAndRuntimeConfigFlow | test_env_and_runtime_config_consistency | P1 | Env vars vs. runtime config consistency |

### Environments (test_environments.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestEnvironmentListDisplay | test_environment_list_display | P0 | Page load + list display |
| TestAddEnvironment | test_add_environment_success | P0 | Add env var successfully |
| TestEditEnvironment | test_edit_environment | P0 | Edit env var |
| TestDeleteEnvironment | test_delete_environment | P0 | Delete env var |
| TestEnvVarMultiRowAndCheckbox | test_env_var_multi_row_and_checkbox | P1 | Multi-row add + checkbox |
| TestEnvVarSaveAndPersist | test_env_var_save_and_persist | P1 | Save persistence |
| TestBatchOperations | test_batch_operations | P1 | Batch operations |
| TestEnvironmentAPI | test_environment_api | P1 | API operations |
| TestEnvKeyDuplicateDetection | test_env_key_duplicate_detection | P1 | Duplicate key detection |
| TestAddEnvironment | test_add_environment_cancel | P2 | Cancel add |
| TestAddEnvironment | test_add_environment_key_required | P2 | Key-required validation |
| TestEnvVarKeyValidation | test_env_var_key_format_validation | P2 | Key format validation |

### Files (test_files.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestFileListEditSave | test_file_list_view_edit_save | P0 | Page load + file list + editor |
| TestFileToggleReorderMemory | test_file_toggle_reorder_memory | P0 | Toggle + drag reorder |
| TestFileContentEditAndSave | test_file_content_edit_save_reset | P0 | File content edit/save/reset |
| TestWorkspaceUploadDownload | test_workspace_download_and_upload_button | P0 | Workspace upload/download |
| TestDailyMemoryView | test_daily_memory_view | P1 | Daily memory expand/collapse view |
| TestMarkdownPreview | test_markdown_preview | P1 | Markdown live preview |
| TestWorkspaceZipUpload | test_workspace_zip_upload | P2 | ZIP upload to restore workspace |
| TestWorkspaceZipDownload | test_workspace_zip_download | P2 | ZIP download of workspace |

### Heartbeat (test_heartbeat.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestHeartbeatDisplayAndToggle | test_heartbeat_display_and_toggle | P0 | Page display + enable/disable |
| TestHeartbeatFullConfig | test_full_heartbeat_configuration | P0 | Full configuration flow |
| TestHeartbeatTargetAndActiveHours | test_target_session_and_active_hours | P2 | Target session and active hours |
| TestHeartbeatIntervalUnit | test_heartbeat_interval_unit | P2 | Interval unit switch (minutes/hours combo) |

### Login (test_login.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestAuthStatus | test_auth_status_api | P0 | Auth status API |
| TestLoginPageAccess | test_login_page_accessible | P0 | Login page accessibility |
| TestMultiUserManagement | test_multi_user_management | P1 | Multi-user management / permissions |
| TestLoginFormValidation | test_login_empty_form_validation | P1 | Empty-form validation |
| TestLoginFormValidation | test_login_partial_form_validation | P1 | Partial-form validation |

### MCP Clients (test_mcp.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestMCPListAndOperations | test_mcp_list_toggle_and_cancel_delete | P0 | List + enable/disable + cancel delete |
| TestCreateMCPClient | test_create_mcp_client_stdio_and_http | P0 | Create dialog + JSON entry |
| TestMCPClientCreateAndDelete | test_create_and_delete_mcp_client | P0 | Create and delete MCP client |
| TestMcpClientEdit | test_mcp_client_edit | P1 | Edit MCP client config |
| TestMcpMultiProtocol | test_mcp_multi_protocol | P1 | Multi-protocol create (stdio/sse/streamable-http) |

### Models (test_models.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestModelListDisplay | test_model_list_display | P0 | Page load + model list |
| TestModelDownload | test_model_download_flow | P0 | Model download flow |
| TestModelServe | test_model_serve_flow | P0 | Start model service |
| TestModelManagement | test_model_management_operations | P0 | Model management operations |
| TestCustomProviderCreateAndDelete | test_custom_provider_create_and_delete | P1 | Create and delete custom provider |
| TestProviderConfigAndConnection | test_provider_config_and_connection_test | P1 | Provider config and connection test |
| TestProviderSearchFilter | test_provider_search_filter | P1 | Provider search filter |
| TestModelActivation | test_model_activation | P1 | Model activation and switching |
| TestOpenRouterFilter | test_openrouter_filter | P2 | OpenRouter filter config |
| TestModelJsonEditor | test_model_json_editor | P2 | JSON config editor |

### Runtime Config (test_runtime_config.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestReActAgentConfig | test_react_agent_language_and_timezone | P0 | ReAct agent language + timezone |
| TestAgentConfigTabSwitch | test_agent_config_tab_switch | P0 | Tab switch validation |
| TestAgentConfigSaveAndReset | test_config_save_and_reset | P0 | Config save and reset |
| TestLlmRetryConfig | test_llm_retry_config | P1 | LLM retry config |
| TestLlmRateLimiterConfig | test_llm_rate_limiter_config | P1 | LLM concurrency rate limit config |
| TestToolResultCompactConfig | test_tool_result_compact_config | P1 | Tool result compaction config |
| TestEmbeddingConfig | test_embedding_config | P1 | Embedding config |
| TestContextCompactConfig | test_context_compact_config | P1 | Context compaction config |
| TestMemorySummaryConfig | test_memory_summary_config | P1 | Memory summary config |
| TestConfigDynamicLinkage | test_config_dynamic_linkage | P2 | Config item dynamic linkage |

### Security (test_security.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestSecurityToolGuardAndTabSwitch | test_tool_guard_toggle_and_tab_switch | P0 | Tool guard + Tab switch |
| TestSecurityFileGuardPathAndToolSelect | test_file_guard_path_add_and_tool_select | P0 | File guard paths + tool selection |
| TestSecurityConfigSaveAndPersist | test_security_config_save_and_persist | P0 | Config save and persistence |
| TestSecurityRuleCrud | test_security_rule_crud | P1 | Security rule CRUD |
| TestSkillScannerModeSwitch | test_skill_scanner_mode_switch | P1 | Skill scanner mode switching |
| TestDeniedToolsConfig | test_denied_tools_config | P1 | Denied tools list config |
| TestRulePreview | test_rule_preview | P1 | Rule preview and match validation |
| TestSecurityBatchRuleToggle | test_security_batch_rule_toggle | P2 | Batch enable/disable rules |

### Sessions (test_sessions.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestSessionListFilterAndDetail | test_session_list_filter_and_detail | P0 | List display + filter + detail |
| TestEditAndDeleteSession | test_edit_and_delete_session | P0 | Edit and delete |
| TestSessionEditAndSave | test_session_edit_name_and_save | P0 | Edit name and save |
| TestSessionBatchDelete | test_session_batch_delete | P1 | Batch delete |
| TestSessionFilterByUseridAndChannel | test_session_filter_by_userid_and_channel | P1 | Filter by user/channel |

### Skill Pool (test_skill_pool.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestSkillPoolPageLoad | test_skill_pool_page_load | P0 | Skill pool page load |
| TestSkillPoolSearch | test_skill_pool_search | P1 | Skill pool search/filter |
| TestSkillPoolInstall | test_skill_pool_install | P1 | Install skill to agent |
| TestSkillPoolBroadcast | test_skill_pool_broadcast | P1 | Broadcast skill to multiple agents |
| TestSkillPoolBatchDelete | test_skill_pool_batch_delete | P1 | Batch delete skills |
| TestSkillPoolZipImport | test_skill_pool_zip_import | P1 | Import skill via ZIP |
| TestSkillPoolBuiltinImport | test_skill_pool_builtin_import | P2 | Import built-in skill pack |

### Skills (test_skills.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestSkillListAndFilter | test_skill_list_filter_and_search | P0 | List display + search filter |
| TestSkillImportToggleDeleteBatch | test_import_toggle_delete_and_batch | P0 | Enable/disable + batch ops |
| TestSkillCRUDLifecycle | test_skill_create_edit_delete | P0 | Skill CRUD lifecycle |
| TestSkillTagManagementAndFilter | test_skill_tag_management_and_filter | P1 | Tag management and filter |
| TestSkillViewToggle | test_skill_view_toggle | P1 | View toggle (card/list) |
| TestSkillImportFromHub | test_skill_import_from_hub | P1 | Import skill from Hub |
| TestSkillPoolSync | test_skill_pool_sync | P1 | Skill pool upload/download sync |
| TestSkillUploadZip | test_skill_upload_via_zip | P1 | Upload skill via ZIP |

### Token Usage (test_token_usage.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestTokenUsageDisplay | test_token_usage_overview | P0 | Token usage overview display |
| TestTokenUsageByModel | test_token_usage_by_model | P1 | Token usage by model |
| TestTokenUsageByDate | test_token_usage_by_date | P1 | Token trend by date |
| TestTokenUsageDateFilter | test_token_usage_date_filter | P1 | Date range filter |
| TestTokenUsageEmptyState | test_token_usage_empty_state | P2 | Empty / loading state display |

### Tools (test_tools.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestToolsPageDisplayAndGlobalToggle | test_tools_page_display_and_global_toggle | P0 | Page display + global toggle |
| TestToolEnableDisableAndAsyncToggle | test_tool_enable_disable_and_async_toggle | P0 | Single tool enable/disable |
| TestToolsGlobalToggleConsistency | test_global_toggle_consistency | P2 | Global toggle consistency |
| TestToolAsyncSwitch | test_tool_async_switch | P2 | Async execution toggle validation |

### Voice (test_voice.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestVoiceConfigDisplay | test_voice_config_display | P0 | Voice config display |
| TestVoiceToggle | test_voice_service_toggle | P0 | Enable/disable voice service |
| TestVoiceServiceConfig | test_twilio_config_form | P0 | Twilio config form |
| TestVoiceModeSwitch | test_voice_mode_switch | P2 | Audio mode switch (auto/native) |

### Debug Logs (test_debug.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestDebugPageDisplay | test_debug_page_load_and_display | P0 | Debug page load and display |
| TestDebugLogControls | test_debug_log_control_buttons | P0 | Log control buttons |
| TestDebugLogLevelFilter | test_debug_log_level_filter | P1 | Log level filter |
| TestDebugLogSearch | test_debug_log_keyword_search | P1 | Log keyword search |
| TestDebugLogFileInfo | test_debug_log_file_info | P1 | Log file info display |

### Backups (test_backups.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestBackupPageDisplay | test_backup_page_load_and_display | P0 | Page load + list display + action buttons |
| TestCreateBackupModalAndCancel | test_create_backup_modal_and_cancel | P0 | Create backup modal + cancel |
| TestCreateFullBackup | test_create_full_backup | P0 | Full backup creation flow |
| TestImportBackupEntry | test_import_backup_entry | P0 | Import backup button and upload entry |
| TestBackupSearchAndFilter | test_backup_search_and_filter | P1 | Backup search and filter |
| TestBackupRestoreModal | test_backup_restore_modal | P1 | Restore modal + restore mode + pre-snapshot |
| TestBackupDeleteAndCancel | test_backup_delete_and_cancel | P1 | Delete and cancel delete |
| TestBackupExport | test_backup_export | P1 | Export functionality |
| TestCreatePartialBackup | test_create_partial_backup_options | P2 | Partial backup (Agent selection) |
| TestBackupListRefreshAndEmpty | test_backup_list_refresh_and_empty | P2 | List refresh and empty state |

### Agent Stats (test_agent_stats.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestAgentStatsPageDisplay | test_agent_stats_page_load_and_cards | P0 | Page load + summary cards |
| TestAgentStatsDatePicker | test_date_range_picker_interaction | P0 | Date range picker interaction |
| TestAgentStatsCharts | test_chart_area_display | P0 | Trend chart area display |
| TestAgentStatsChannelDistribution | test_channel_distribution_display | P1 | Channel distribution pie chart |
| TestAgentStatsDateFilter | test_date_filter_refreshes_data | P1 | Data refresh after date filter |
| TestAgentStatsCardTooltip | test_card_tooltip_display | P1 | Summary card tooltip |
| TestAgentStatsEmptyAndLoading | test_empty_and_loading_states | P2 | Empty and loading states |
| TestAgentStatsRefresh | test_page_refresh_data_persistence | P2 | Data persistence after page refresh |

### ACP Config (test_acp.py)
| Test Class | Test Method | Priority | Coverage |
|------------|-------------|----------|----------|
| TestACPPageDisplay | test_acp_page_load_and_card_list | P0 | Page load + card list + built-in ACP |
| TestCreateACPDrawerForm | test_create_acp_drawer_form | P0 | Create drawer form validation |
| TestACPToggleSwitch | test_acp_toggle_switch | P0 | Toggle enable/disable + restore |
| TestACPFilterTabs | test_filter_tabs_switch | P1 | Filter tabs switch (All/Builtin/Custom) |
| TestEditACPConfig | test_edit_acp_config | P1 | Edit ACP config |
| TestCreateAndDeleteCustomACP | test_create_and_delete_custom_acp | P1 | Create and delete custom ACP |
| TestBuiltinACPProtection | test_builtin_acp_protection | P2 | Built-in ACP protection |
| TestACPCardDetails | test_acp_card_content_details | P2 | ACP card content details |

---

## Test Execution Results

- **Latest full run**: 2026-04-27
- **Total cases**: 172
- **Passed**: pending
- **Failed**: pending
- **Skipped**: pending
- **Pass rate**: pending
