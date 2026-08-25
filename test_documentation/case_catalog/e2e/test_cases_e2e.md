# E2E 测试用例目录

**总计**: 206 条用例

---

## ACP 模块

用例数：8

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_acp_page_load_and_card_list | test_acp_page_load_and_card_list | P0 | Verify ACP page load and card list display. |  |
| test_create_acp_drawer_form | test_create_acp_drawer_form | P0 | Verify create ACP drawer form. |  |
| test_acp_toggle_switch | test_acp_toggle_switch | P0 | Verify ACP enable/disable toggle. |  |
| test_filter_tabs_switch | test_filter_tabs_switch | P0 | Verify filter tab switching. |  |
| test_edit_acp_config | test_edit_acp_config | P0 | Verify edit ACP configuration. |  |
| test_create_and_delete_custom_acp | test_create_and_delete_custom_acp | P0 | Verify create and delete custom ACP. |  |
| test_builtin_acp_protection | test_builtin_acp_protection | P0 | Verify builtin ACP protection mechanism. |  |
| test_acp_card_content_details | test_acp_card_content_details | P0 | Verify ACP card content details. |  |

### 详细用例

#### test_acp_page_load_and_card_list: test_acp_page_load_and_card_list

**优先级**: P0

**测试目的**: Verify ACP page load and card list display.

**校验点**:

- Page should contain All tab
- Create button should be visible
- ACP card list should not be empty (at least builtin ACP expected)
- Assertion check

---

#### test_create_acp_drawer_form: test_create_acp_drawer_form

**优先级**: P0

**测试目的**: Verify create ACP drawer form.

**校验点**:

- Create button not visible, cannot continue
- command input should be visible
- agentKey should be editable when creating

---

#### test_acp_toggle_switch: test_acp_toggle_switch

**优先级**: P0

**测试目的**: Verify ACP enable/disable toggle.

**校验点**:

- Assertion check

---

#### test_filter_tabs_switch: test_filter_tabs_switch

**优先级**: P0

**测试目的**: Verify filter tab switching.

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

#### test_edit_acp_config: test_edit_acp_config

**优先级**: P0

**测试目的**: Verify edit ACP configuration.

**校验点**:

- Edit drawer should have command input
- command should have a value in edit mode
- agentKey should have a value in edit mode
- Edit drawer should have a title

---

#### test_create_and_delete_custom_acp: test_create_and_delete_custom_acp

**优先级**: P0

**测试目的**: Verify create and delete custom ACP.

**校验点**:

- Create button not visible, cannot continue

---

#### test_builtin_acp_protection: test_builtin_acp_protection

**优先级**: P0

**测试目的**: Verify builtin ACP protection mechanism.

**校验点**:

- Builtin ACP agentKey should be disabled or readonly
- Builtin ACP agentKey should be hidden or non-editable
- Builtin ACP delete button should be disabled

---

#### test_acp_card_content_details: test_acp_card_content_details

**优先级**: P0

**测试目的**: Verify ACP card content details.

**校验点**:

- ACP card list should not be empty
- At least some ACP cards should contain agentKey identifier or enable/disable switch
- Assertion check

---

## AGENT_STATS 模块

用例数：8

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_agent_stats_page_load_and_cards | test_agent_stats_page_load_and_cards | P0 | Verify agent stats page load and summary cards dis... |  |
| test_date_range_picker_interaction | test_date_range_picker_interaction | P0 | Verify date range picker interaction. |  |
| test_chart_area_display | test_chart_area_display | P0 | Verify trend chart area display. |  |
| test_channel_distribution_display | test_channel_distribution_display | P0 | Verify channel distribution pie chart display. |  |
| test_date_filter_refreshes_data | test_date_filter_refreshes_data | P0 | Verify data refresh after date filter. |  |
| test_card_tooltip_display | test_card_tooltip_display | P0 | Verify summary card tooltip. |  |
| test_empty_and_loading_states | test_empty_and_loading_states | P0 | Verify empty state and loading state display. |  |
| test_page_refresh_data_persistence | test_page_refresh_data_persistence | P0 | Verify data persistence after page refresh. |  |

### 详细用例

#### test_agent_stats_page_load_and_cards: test_agent_stats_page_load_and_cards

**优先级**: P0

**测试目的**: Verify agent stats page load and summary cards display.

**校验点**:

- Page should display summary cards or empty state
- Breadcrumb should contain Settings
- Breadcrumb should contain Agent Stats/Statistics
- Summary cards should contain at least one key metric (Sessions/Messages/Tokens)

---

#### test_date_range_picker_interaction: test_date_range_picker_interaction

**优先级**: P0

**测试目的**: Verify date range picker interaction.

**校验点**:

- Date range picker should be visible
- Calendar panel should pop up after clicking date picker
- Calendar panel should contain date cells
- Calendar panel should contain date content

---

#### test_chart_area_display: test_chart_area_display

**优先级**: P0

**测试目的**: Verify trend chart area display.

**校验点**:

- Page should display chart elements (canvas/svg/container) or empty state
- Assertion check

---

#### test_channel_distribution_display: test_channel_distribution_display

**优先级**: P0

**测试目的**: Verify channel distribution pie chart display.

**校验点**:

- Page should contain channel distribution area or display empty state

---

#### test_date_filter_refreshes_data: test_date_filter_refreshes_data

**优先级**: P0

**测试目的**: Verify data refresh after date filter.

**校验点**:

- Date picker should be visible
- After date filter, should still have cards or display empty state

---

#### test_card_tooltip_display: test_card_tooltip_display

**优先级**: P0

**测试目的**: Verify summary card tooltip.

**校验点**:

- Tooltip content should not be empty

---

#### test_empty_and_loading_states: test_empty_and_loading_states

**优先级**: P0

**测试目的**: Verify empty state and loading state display.

**校验点**:

- Page should display data cards, empty state, or error state after loading

---

#### test_page_refresh_data_persistence: test_page_refresh_data_persistence

**优先级**: P0

**测试目的**: Verify data persistence after page refresh.

**校验点**:

- Assertion check

---

## AGENTS 模块

用例数：12

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_agent_list_display_and_refresh | test_agent_list_display_and_refresh | P0 | Verify agent list display and refresh. | Agents management page access and load, Agent list display (name, ID, description, status), List refresh |
| test_create_agent_success | test_create_agent_success | P0 | Verify agent is created successfully. | Click the Create Agent button, Fill the form (name, description, language), Submit the form |
| test_create_agent_cancel | test_create_agent_cancel | P0 | Verify cancelling agent creation. | Click the Create Agent button, Fill the form (name, description, language), Submit the form |
| test_create_agent_name_required | test_create_agent_name_required | P0 | Verify that the agent name is required. | Click the Create Agent button, Fill the form (name, description, language), Submit the form |
| test_edit_agent_info | test_edit_agent_info | P0 | Verify editing agent info. | Edit-agent entry point, Modify agent name, Modify agent description |
| test_delete_agent_success | test_delete_agent_success | P0 | Verify agent is deleted successfully. | Delete-agent entry point, Delete confirmation dialog, Confirm delete |
| test_delete_agent_cancel | test_delete_agent_cancel | P0 | Verify cancelling agent deletion. | Delete-agent entry point, Delete confirmation dialog, Confirm delete |
| test_toggle_agent_status | test_toggle_agent_status | P0 | Verify toggling the agent's enabled state. | Display agent status, Toggle agent status, Verify status update |
| test_agent_api_operations | test_agent_api_operations | P0 | Verify agent API operations. | API: list agents, API: create agent, API: delete agent |
| test_default_agent_protected | test_default_agent_protected | P0 | Verify that the default agent is protected. | Default agent cannot be deleted, Default agent cannot be disabled |
| test_agent_drag_reorder | test_agent_drag_reorder | P0 | Test agent drag-and-drop reordering. | Identify drag handles in the agent list, Perform drag operation (from position A to position B), Verify the new order |
| test_agent_skill_association | test_agent_skill_association | P0 | Test the agent skill association config. |  |

### 详细用例

#### test_agent_list_display_and_refresh: test_agent_list_display_and_refresh

**优先级**: P0

**测试目的**: Verify agent list display and refresh.

**校验点**:

- Agent list should contain at least one agent (default)
- Agent list should not be empty
- Agents should have a name
- Agent count should match before and after refresh

---

#### test_create_agent_success: test_create_agent_success

**优先级**: P0

**测试目的**: Verify agent is created successfully.

**校验点**:

- Create success message should be shown
- Assertion check
- Assertion check

---

#### test_create_agent_cancel: test_create_agent_cancel

**优先级**: P0

**测试目的**: Verify cancelling agent creation.

**校验点**:

- Agent count should not change after cancel

---

#### test_create_agent_name_required: test_create_agent_name_required

**优先级**: P0

**测试目的**: Verify that the agent name is required.

**校验点**:

- Empty name should either show an error or block submission

---

#### test_edit_agent_info: test_edit_agent_info

**优先级**: P0

**测试目的**: Verify editing agent info.

**校验点**:

- Test agent should be created
- Edit success message should be shown

---

#### test_delete_agent_success: test_delete_agent_success

**优先级**: P0

**测试目的**: Verify agent is deleted successfully.

**校验点**:

- Test agent should be created
- Delete success message should be shown
- Assertion check
- Assertion check

---

#### test_delete_agent_cancel: test_delete_agent_cancel

**优先级**: P0

**测试目的**: Verify cancelling agent deletion.

**校验点**:

- Assertion check
- Agent count should not change after cancel delete

---

#### test_toggle_agent_status: test_toggle_agent_status

**优先级**: P0

**测试目的**: Verify toggling the agent's enabled state.

**校验点**:

- Test agent should exist
- Agent should be disabled (data-status='disabled' or success message should appear)
- Agent should be enabled (disabled dot should disappear)

---

#### test_agent_api_operations: test_agent_api_operations

**优先级**: P0

**测试目的**: Verify agent API operations.

**校验点**:

- API should return a list
- API create should return a result
- Assertion check
- Should be able to obtain the agent ID
- API delete should return a result

---

#### test_default_agent_protected: test_default_agent_protected

**优先级**: P0

**测试目的**: Verify that the default agent is protected.

**校验点**:

- Default agent's delete button should be disabled

---

#### test_agent_drag_reorder: test_agent_drag_reorder

**优先级**: P0

**测试目的**: Test agent drag-and-drop reordering.

**校验点**:

- Could not read >=2 agent keys
- Could not read the position of the second row
- Agent order did not change after drag; reorder did not take effect
- Assertion check

---

#### test_agent_skill_association: test_agent_skill_association

**优先级**: P0

**测试目的**: Test the agent skill association config.

**校验点**:

- Assertion check
- Detail view should have interactive elements
- Skills section should be visible

---

## BACKUPS 模块

用例数：10

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_backup_page_load_and_display | test_backup_page_load_and_display | P0 | Verify backups page loads and displays the list. |  |
| test_create_backup_modal_and_cancel | test_create_backup_modal_and_cancel | P0 | Verify the create-backup modal and cancel. |  |
| test_create_full_backup | test_create_full_backup | P0 | Verify the full create-backup -> restore -> delete... |  |
| test_import_backup_entry | test_import_backup_entry | P0 | Verify import backup button and file upload entry. |  |
| test_backup_search_and_filter | test_backup_search_and_filter | P0 | Verify backup search and filter. |  |
| test_backup_restore_modal | test_backup_restore_modal | P0 | Verify the backup restore modal. |  |
| test_backup_delete_and_cancel | test_backup_delete_and_cancel | P0 | Verify backup delete and cancel delete. |  |
| test_backup_export | test_backup_export | P0 | Verify backup export. |  |
| test_create_partial_backup_options | test_create_partial_backup_options | P0 | Verify partial backup options display. |  |
| test_backup_list_refresh_and_empty | test_backup_list_refresh_and_empty | P0 | Verify backup list refresh and empty state. |  |

### 详细用例

#### test_backup_page_load_and_display: test_backup_page_load_and_display

**优先级**: P0

**测试目的**: Verify backups page loads and displays the list.

**校验点**:

- Breadcrumb should contain Settings
- Breadcrumb should contain Backups
- Table should have column headers

---

#### test_create_backup_modal_and_cancel: test_create_backup_modal_and_cancel

**优先级**: P0

**测试目的**: Verify the create-backup modal and cancel.

**校验点**:

- Assertion check

---

#### test_create_full_backup: test_create_full_backup

**优先级**: P0

**测试目的**: Verify the full create-backup -> restore -> delete flow.

**校验点**:

- Could not confirm backup creation (no progress bar, success message, or modal close)
- Assertion check

---

#### test_import_backup_entry: test_import_backup_entry

**优先级**: P0

**测试目的**: Verify import backup button and file upload entry.

**校验点**:

- No import backup entry found (button or file upload)

---

#### test_backup_search_and_filter: test_backup_search_and_filter

**优先级**: P0

**测试目的**: Verify backup search and filter.

**校验点**:

- Assertion check
- Assertion check

---

#### test_backup_restore_modal: test_backup_restore_modal

**优先级**: P0

**测试目的**: Verify the backup restore modal.

**校验点**:

- A modal or confirm dialog should appear after clicking restore
- Assertion check

---

#### test_backup_delete_and_cancel: test_backup_delete_and_cancel

**优先级**: P0

**测试目的**: Verify backup delete and cancel delete.

**校验点**:

- Assertion check

---

#### test_backup_export: test_backup_export

**优先级**: P0

**测试目的**: Verify backup export.

**校验点**:

- Export did not trigger successfully
- Download filename should not be empty

---

#### test_create_partial_backup_options: test_create_partial_backup_options

**优先级**: P0

**测试目的**: Verify partial backup options display.

**校验点**:

- Partial backup mode should display config options (name, description, selectors, etc.)

---

#### test_backup_list_refresh_and_empty: test_backup_list_refresh_and_empty

**优先级**: P0

**测试目的**: Verify backup list refresh and empty state.

**校验点**:

- Assertion check
- Empty state should persist after reload

---

## CHANNELS 模块

用例数：10

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_channel_list_filter_and_type | test_channel_list_filter_and_type | unknown | Verify channel list display, filter switching, and... |  |
| test_console_edit_save_cancel | test_console_edit_save_cancel | unknown | Verify Console channel edit drawer opening, form f... |  |
| test_discord_enable_disable_ui | test_discord_enable_disable_ui | unknown | Verify Discord channel enable/disable switch UI to... |  |
| test_four_channels_form_fields | test_four_channels_form_fields | unknown | Verify the config form-field differences across Di... |  |
| test_mattermost_filter_edit_cancel | test_mattermost_filter_edit_cancel | unknown | Verify the Mattermost edit+cancel combination unde... |  |
| test_message_filter_switches | test_message_filter_switches | unknown | Iterate all channels, find ones with message-filte... |  |
| test_wecom_form_fields | test_wecom_form_fields | unknown | Verify the WeCom channel's drawer config form fiel... |  |
| test_wechat_form_fields | test_wechat_form_fields | unknown | Verify the WeChat channel's drawer config form fie... |  |
| test_onebot_form_fields | test_onebot_form_fields | unknown | Verify the OneBot channel's drawer config form fie... |  |
| test_mqtt_bot_prefix | test_mqtt_bot_prefix | unknown | Verify the MQTT channel's Bot Prefix configuration... |  |

### 详细用例

#### test_channel_list_filter_and_type: test_channel_list_filter_and_type

**优先级**: unknown

**测试目的**: Verify channel list display, filter switching, and channel-type tag.

**业务场景**: The user opens the Channels page, browses the channel list, uses the filters to quickly locate built-in or custom channels, and confirms that the channel-type tag is displayed correctly.

**测试流程**:

1. Open the Channels page and verify the page title
2. Verify the All / Built-in / Custom filter buttons are visible
3. Under the default All view there are >= 15 channel cards
4. Verify several built-in channels show the Built-in tag
5. Click the Built-in filter and verify results are all built-in channels
6. Click the Custom filter and verify results are all custom channels (may be empty)
7. Click the All filter and verify all channels are restored

**校验点**:

- Assertion check
- All filter button not shown
- Built-in filter button not shown
- Custom filter button not shown
- Assertion check

---

#### test_console_edit_save_cancel: test_console_edit_save_cancel

**优先级**: unknown

**测试目的**: Verify Console channel edit drawer opening, form filling, save and cancel.

**业务场景**: Console is the only Enabled channel with no required fields, so the user can save the config directly. Verify that saved config persists and that a cancel operation does not modify the saved config.

**测试流程**:

1. Open the Channels page
2. Click the Console card and verify the drawer opens and title
3. Verify form fields (Enable switch + Bot Prefix input)
4. Record the original Bot Prefix, modify and save
5. Reload the page and reopen the drawer, verify the save took effect
6. Reopen the drawer, modify and cancel, verify config is unchanged
7. Restore the original value

**校验点**:

- Edit drawer did not open
- Assertion check
- Bot Prefix input not visible
- Enable switch does not exist
- Assertion check

---

#### test_discord_enable_disable_ui: test_discord_enable_disable_ui

**优先级**: unknown

**测试目的**: Verify Discord channel enable/disable switch UI toggling.

**业务场景**: The user tries to enable/disable the Discord channel, but missing required fields (Client ID/Secret) cause save to fail. Verify that the switch UI toggles but the config is not persisted.

**测试流程**:

1. Open the Channels page
2. Click the Discord card and verify the drawer opens
3. Read the current switch state
4. Toggle the switch and verify aria-checked change
5. Try to save (expected to fail because required fields are empty)
6. Close the drawer, reopen it, and verify the switch state was not persisted

**校验点**:

- Edit drawer did not open
- Assertion check
- Assertion check
- Assertion check

---

#### test_four_channels_form_fields: test_four_channels_form_fields

**优先级**: unknown

**测试目的**: Verify the config form-field differences across DingTalk, Feishu, Telegram, QQ.

**业务场景**: Different channels have different config form fields. Verify each channel's form fields exist and are distinctive.

**测试流程**:

1. Open the Channels page
2. Open the four channel drawers in turn and verify each has its own distinctive form fields
3. Close each drawer before moving on to the next

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

#### test_mattermost_filter_edit_cancel: test_mattermost_filter_edit_cancel

**优先级**: unknown

**测试目的**: Verify the Mattermost edit+cancel combination under the Built-in filter.

**业务场景**: Under the Built-in filter the user finds the Mattermost channel, opens the edit drawer, modifies Bot Prefix and cancels, and verifies that the cancel did not modify the config.

**测试流程**:

1. Open the Channels page
2. Click the Built-in filter
3. Find the Mattermost card and click it
4. Verify the drawer opens
5. Record the original Bot Prefix
6. Modify Bot Prefix and cancel
7. Reopen the drawer and verify Bot Prefix is unchanged

**校验点**:

- Assertion check
- Assertion check
- Assertion check
- Assertion check

---

#### test_message_filter_switches: test_message_filter_switches

**优先级**: unknown

**测试目的**: Iterate all channels, find ones with message-filter switches and verify they can be toggled.

**业务场景**: Some channels have message-filter switches (Show Tool Messages / Show Thinking). Verify these switches can be toggled in the UI.

**测试流程**:

1. Open the Channels page
2. Get all channel cards
3. For each channel, open the drawer and check for 'Show Tool Messages' or 'Show Thinking' switches
4. If found, verify the switch can be toggled
5. At least one channel with such a switch must be found

**校验点**:

- No channel with a message-filter switch was found
- Assertion check

---

#### test_wecom_form_fields: test_wecom_form_fields

**优先级**: unknown

**测试目的**: Verify the WeCom channel's drawer config form fields.

**业务场景**: Verify that the WeCom channel's config form fields are displayed correctly.

**测试流程**:

1. Open the Channels page
2. Click the WeCom card and verify the drawer opens
3. Verify the drawer title contains WeCom
4. Verify the form fields exist

**校验点**:

- Edit drawer did not open
- Assertion check
- Assertion check

---

#### test_wechat_form_fields: test_wechat_form_fields

**优先级**: unknown

**测试目的**: Verify the WeChat channel's drawer config form fields.

**业务场景**: Verify that the WeChat channel's config form fields are displayed correctly.

**测试流程**:

1. Open the Channels page
2. Click the WeChat card and verify the drawer opens
3. Verify the drawer title contains WeChat
4. Verify the form fields exist

**校验点**:

- Edit drawer did not open
- Assertion check
- Assertion check

---

#### test_onebot_form_fields: test_onebot_form_fields

**优先级**: unknown

**测试目的**: Verify the OneBot channel's drawer config form fields.

**业务场景**: Verify that the OneBot channel's config form fields are displayed correctly.

**测试流程**:

1. Open the Channels page
2. Click the OneBot card and verify the drawer opens
3. Verify the drawer title contains OneBot
4. Verify the form fields exist

**校验点**:

- Edit drawer did not open
- Assertion check
- Assertion check

---

#### test_mqtt_bot_prefix: test_mqtt_bot_prefix

**优先级**: unknown

**测试目的**: Verify the MQTT channel's Bot Prefix configuration.

**业务场景**: Verify the Bot Prefix configuration for the MQTT channel.

**测试流程**:

1. Open the Channels page
2. Click the MQTT card and verify the drawer opens
3. Verify the drawer title contains MQTT
4. Verify the Bot Prefix field exists
5. Modify Bot Prefix and cancel, verify non-persistence

**校验点**:

- Edit drawer did not open
- Assertion check
- Bot Prefix input not visible
- Assertion check

---

## CHAT 模块

用例数：14

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_new_chat_basic_qa_copy | test_new_chat_basic_qa_copy | P0 | Verify the full flow: new chat, send message, rece... | New chat (CHAT-001), Basic text Q&A (CHAT-002), Copy message (CHAT-008) |
| test_multi_turn_context_awareness | test_multi_turn_context_awareness | P0 | Verify the AI handles context correctly in multi-t... | Multi-turn conversation (CHAT-004), Context understanding and memory |
| test_upload_file_and_ask_questions | test_upload_file_and_ask_questions | P0 | Verify Q&A based on uploaded file content. | Attachment upload (CHAT-007), File preview, Intelligent Q&A based on file content |
| test_session_rename_pin_delete_switch | test_session_rename_pin_delete_switch | P0 | Verify the full session lifecycle management. | View session list, Rename session, Pin session |
| test_model_switch_and_skill_invocation | test_model_switch_and_skill_invocation | P0 | Verify model switching and skill invocation. | Model selection and switching (CHAT-005), Agent switching (CHAT-006), Skill invocation (CHAT-011 ~ CHAT-022) |
| test_input_validation_and_special_chars | test_input_validation_and_special_chars | P0 | Verify special character and code block input hand... | Special character handling, Code block input handling |
| test_chat_message_search | test_chat_message_search | P0 | Verify message search. | Open the search panel, Enter a keyword to search, Verify search results |
| test_chat_message_edit | test_chat_message_edit | P0 | Test message edit / regenerate. | After sending a message, find the edit/regenerate button, Verify the button exists and is clickable |
| test_chat_stop_generation | test_chat_stop_generation | P0 | Test stream interruption / stop generation. | Verify the presence of the stop-generation button, Verify the input area has a send button |
| test_chat_long_message | test_chat_long_message | P0 | Test very long message input. | Type a very long text into the input box, Verify the input box can accept it |
| test_chat_ime_input | test_chat_ime_input | P0 | Test IME composition events. | Verify the input box supports Chinese input, Verify the input box does not submit during IME composition |
| test_approval_toggle_renders_and_switches | test_approval_toggle_renders_and_switches | P0 | Toggle renders, exposes 4 levels, and the Tag foll... |  |
| test_approval_level_persists_across_reload | test_approval_level_persists_across_reload | P0 | A selected level is stored in localStorage and sur... |  |
| test_approval_level_cleared_on_session_delete | test_approval_level_cleared_on_session_delete | P0 | Deleting a session removes its ``approval_level-<i... |  |

### 详细用例

#### test_new_chat_basic_qa_copy: test_new_chat_basic_qa_copy

**优先级**: P0

**测试目的**: Verify the full flow: new chat, send message, receive response, copy message.

**业务场景**: The user opens the Chat page, creates a new chat, sends a question, receives an AI response, and copies the response for other uses.

**测试流程**:

1. Open the Chat page
2. Click the New Chat button
3. Verify the welcome screen
4. Send a basic text message
5. Wait for the AI response
6. Verify message display
7. Copy the AI response
8. Verify the message history

**校验点**:

- Welcome screen not shown
- AI response timed out
- User message not shown
- AI message not shown
- Message history is incomplete

---

#### test_multi_turn_context_awareness: test_multi_turn_context_awareness

**优先级**: P0

**测试目的**: Verify the AI handles context correctly in multi-turn chat.

**业务场景**: The user has a multi-turn conversation; the AI must understand context and reply coherently.

**测试流程**:

1. Open the Chat page and create a new chat
2. Send the first-round message
3. Send a context-dependent follow-up
4. Verify the conversation history is complete

**校验点**:

- Assertion check
- Assertion check

---

#### test_upload_file_and_ask_questions: test_upload_file_and_ask_questions

**优先级**: P0

**测试目的**: Verify Q&A based on uploaded file content.

**业务场景**: The user uploads a document and then asks questions about its content.

**测试流程**:

1. Open the Chat page
2. Upload a file
3. Verify the file upload succeeded
4. Ask a question based on the file content
5. Verify the AI response contains file-related content

**校验点**:

- File upload failed
- AI response timed out
- Assertion check

---

#### test_session_rename_pin_delete_switch: test_session_rename_pin_delete_switch

**优先级**: P0

**测试目的**: Verify the full session lifecycle management.

**业务场景**: The user manages multiple sessions: renaming, pinning important sessions, deleting unused ones, and switching between sessions.

**测试流程**:

1. Open the Chat page
2. Create the first session and send a message
3. Create the second session and send a message
4. Open the session list and verify the count
5. Rename the first session
6. Pin the first session and verify pinned state
7. Switch to another session and verify its content
8. Delete the last session and verify deletion succeeded

**校验点**:

- Assertion check
- Pinned marker not shown
- Session has no messages after switching
- Assertion check

---

#### test_model_switch_and_skill_invocation: test_model_switch_and_skill_invocation

**优先级**: P0

**测试目的**: Verify model switching and skill invocation.

**业务场景**: The user switches between models as needed, invokes skills to complete specific tasks, and inspects tool call details.

**测试流程**:

1. Open the Chat page
2. Open the model selector
3. Select a different model (if multiple are available)
4. Send /skills command to inspect available skills
5. Verify the skill list is displayed
6. Test tool call detail expand/collapse

**校验点**:

- No response after switching models
- AI response empty after switching models
- No response to skills query
- Skills response is empty

---

#### test_input_validation_and_special_chars: test_input_validation_and_special_chars

**优先级**: P0

**测试目的**: Verify special character and code block input handling.

**业务场景**: Verify the system handles special characters and code-block input.

**测试流程**:

1. Open the Chat page
2. Test special character input
3. Test code block input

**校验点**:

- No AI response for special-character message
- AI response empty for special-character message
- Special-character message not shown in the chat
- No AI response for code-block message
- AI response empty for code-block message

---

#### test_chat_message_search: test_chat_message_search

**优先级**: P0

**测试目的**: Verify message search.

**业务场景**: In a long conversation the user uses search to quickly locate messages containing a specific keyword.

**测试流程**:

1. Open the Chat page and create a new chat
2. Send a message containing a specific keyword
3. Wait for the AI response
4. Click the search button to open the search panel
5. Type the keyword in the search box
6. Verify the search results contain matches
7. Click a search result to jump to the corresponding message
8. Close the search panel

**校验点**:

- AI response timed out
- Assertion check
- Assertion check
- Assertion check

---

#### test_chat_message_edit: test_chat_message_edit

**优先级**: P0

**测试目的**: Test message edit / regenerate.

**校验点**:

- Input area should be visible
- Input area should be enabled

---

#### test_chat_stop_generation: test_chat_stop_generation

**优先级**: P0

**测试目的**: Test stream interruption / stop generation.

**校验点**:

- Chat page should have an input area
- Input area should be enabled (can submit with Enter)

---

#### test_chat_long_message: test_chat_long_message

**优先级**: P0

**测试目的**: Test very long message input.

**校验点**:

- Assertion check

---

#### test_chat_ime_input: test_chat_ime_input

**优先级**: P0

**测试目的**: Test IME composition events.

**校验点**:

- Assertion check

---

#### test_approval_toggle_renders_and_switches: test_approval_toggle_renders_and_switches

**优先级**: P0

**测试目的**: Toggle renders, exposes 4 levels, and the Tag follows the choice.

**校验点**:

- Assertion check

---

#### test_approval_level_persists_across_reload: test_approval_level_persists_across_reload

**优先级**: P0

**测试目的**: A selected level is stored in localStorage and survives a reload.

**校验点**:

- Assertion check
- Assertion check

---

#### test_approval_level_cleared_on_session_delete: test_approval_level_cleared_on_session_delete

**优先级**: P0

**测试目的**: Deleting a session removes its ``approval_level-<id>`` localStorage key.

**校验点**:

- Assertion check
- Assertion check

---

## CHAT_SIDEBAR 模块

用例数：2

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_sidebar_date_groups_and_collapse | test_sidebar_date_groups_and_collapse | P1 | Upstream re-architected the sidebar into user grou... |  |
| test_non_owner_tab_shows_queue_banner | test_non_owner_tab_shows_queue_banner | P1 |  |  |

### 详细用例

#### test_sidebar_date_groups_and_collapse: test_sidebar_date_groups_and_collapse

**优先级**: P1

**测试目的**: Upstream re-architected the sidebar into user groups that each

---

#### test_non_owner_tab_shows_queue_banner: test_non_owner_tab_shows_queue_banner

**优先级**: P1

**测试目的**: 

---

## CODING 模块

用例数：5

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_enter_and_exit_coding_mode | test_enter_and_exit_coding_mode | P0 |  |  |
| test_create_empty_project_and_open | test_create_empty_project_and_open | P0 |  |  |
| test_open_existing_directory | test_open_existing_directory | P0 |  |  |
| test_chat_in_coding_mode_with_file_reference | test_chat_in_coding_mode_with_file_reference | P0 |  |  |
| test_file_tree_open_and_edit_tab | test_file_tree_open_and_edit_tab | P0 |  |  |

### 详细用例

#### test_enter_and_exit_coding_mode: test_enter_and_exit_coding_mode

**优先级**: P0

**测试目的**: 

**校验点**:

- IDE rail should be absent while Coding Mode is off
- Coding Mode IDE surface did not render after enabling
- Expected Coding Mode IDE surface to be active
- Expected IDE rail to disappear after disabling Coding Mode

---

#### test_create_empty_project_and_open: test_create_empty_project_and_open

**优先级**: P0

**测试目的**: 

**校验点**:

- IDE shell did not render after creating project

---

#### test_open_existing_directory: test_open_existing_directory

**优先级**: P0

**测试目的**: 

**校验点**:

- Assertion check
- IDE surface did not render after opening existing directory

---

#### test_chat_in_coding_mode_with_file_reference: test_chat_in_coding_mode_with_file_reference

**优先级**: P0

**测试目的**: 

**校验点**:

- IDE surface did not render

---

#### test_file_tree_open_and_edit_tab: test_file_tree_open_and_edit_tab

**优先级**: P0

**测试目的**: 

**校验点**:

- IDE surface did not render

---

## CRONJOBS 模块

用例数：8

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_cronjob_lifecycle | test_cronjob_lifecycle | P0 | Verify the full cron job lifecycle: create -> list... |  |
| test_toggle_and_execute | test_toggle_and_execute | P0 | Verify enable/disable toggle and run-now. |  |
| test_schedule_type_and_task_type | test_schedule_type_and_task_type | P0 | Verify schedule type switching and task type behav... |  |
| test_cronjob_schedule_type_switch | test_cronjob_schedule_type_switch | P0 | Test the cron job schedule type switching behavior... | When creating a cron job, choose different schedule types (daily/weekly/custom), Verify form fields show/hide based on the selected type, daily: time picker |
| test_cronjob_edit_and_update | test_cronjob_edit_and_update | P0 | Test the cron job edit and update flow. | Create a test job, Open the edit drawer from the more menu, Modify the job name and description |
| test_cronjob_weekly_schedule | test_cronjob_weekly_schedule | P0 | Test weekly schedule and multi-day selection. |  |
| test_cronjob_json_params | test_cronjob_json_params | P0 | Test the JSON request parameter input. |  |
| test_cronjob_timezone | test_cronjob_timezone | P0 | Test timezone selection and switching. |  |

### 详细用例

#### test_cronjob_lifecycle: test_cronjob_lifecycle

**优先级**: P0

**测试目的**: Verify the full cron job lifecycle: create -> list -> edit -> delete.

**测试流程**:

1. Visit CronJobs page, verify table loads and columns are shown
2. Create a cron job (every day at 9am)
3. Verify the job appears in the list
4. Edit the job, change the Cron expression to 6pm daily
5. Verify the edit took effect
6. Delete the job
7. Verify the job was deleted

**校验点**:

- Assertion check
- Assertion check
- Action buttons should be present

---

#### test_toggle_and_execute: test_toggle_and_execute

**优先级**: P0

**测试目的**: Verify enable/disable toggle and run-now.

**测试流程**:

1. Visit CronJobs page, create a test job
2. Verify the job was created
3. Verify the enable button is available
4. Click the enable button to toggle state
5. Verify the run-now button is available

**校验点**:

- Assertion check
- Cron job row should include an enable/disable button
- Assertion check
- Run-now button should be enabled

---

#### test_schedule_type_and_task_type: test_schedule_type_and_task_type

**优先级**: P0

**测试目的**: Verify schedule type switching and task type behavior.

**测试流程**:

1. Visit the CronJobs page
2. Click the create-job button to open the drawer
3. Verify the drawer opens
4. Fill in the job name
5. Verify the schedule type selector exists
6. Select "daily" and verify the time picker appears
7. Select "weekly" and verify the weekday picker appears
8. Select "custom" and verify the cron expression input appears
9. Verify the task type selector exists
10. Select "text" and verify the text input appears
11. Select "agent" and verify the JSON input appears
12. Cancel and close the drawer

---

#### test_cronjob_schedule_type_switch: test_cronjob_schedule_type_switch

**优先级**: P0

**测试目的**: Test the cron job schedule type switching behavior.

**校验点**:

- Create-job button not found
- Create-job dialog or drawer did not open
- No input fields found in the create form
- Assertion check
- Schedule type dropdown options are empty

---

#### test_cronjob_edit_and_update: test_cronjob_edit_and_update

**优先级**: P0

**测试目的**: Test the cron job edit and update flow.

**校验点**:

- Assertion check

---

#### test_cronjob_weekly_schedule: test_cronjob_weekly_schedule

**优先级**: P0

**测试目的**: Test weekly schedule and multi-day selection.

**校验点**:

- Weekly schedule type should have weekday checkboxes

---

#### test_cronjob_json_params: test_cronjob_json_params

**优先级**: P0

**测试目的**: Test the JSON request parameter input.

**校验点**:

- Create form should have a JSON input area
- JSON input should be filled with content

---

#### test_cronjob_timezone: test_cronjob_timezone

**优先级**: P0

**测试目的**: Test timezone selection and switching.

**校验点**:

- Timezone dropdown options should not be empty

---

## CROSS_MODULE 模块

用例数：6

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_skill_to_agent_to_chat | test_skill_to_agent_to_chat | unknown | Verify that a created skill can be linked in an ag... |  |
| test_model_switch_and_chat_continuity | test_model_switch_and_chat_continuity | unknown | Verify Chat continues to work after switching mode... |  |
| test_security_config_affects_chat | test_security_config_affects_chat | unknown | Verify the linkage between security guard config a... |  |
| test_workspace_file_and_chat_qa | test_workspace_file_and_chat_qa | unknown | Verify linkage between workspace files and Chat fi... |  |
| test_env_and_runtime_config_consistency | test_env_and_runtime_config_consistency | unknown | Verify consistency between environment variables a... |  |
| test_agent_switcher_in_chat | test_agent_switcher_in_chat | unknown |  |  |

### 详细用例

#### test_skill_to_agent_to_chat: test_skill_to_agent_to_chat

**优先级**: unknown

**测试目的**: Verify that a created skill can be linked in an agent and invoked in Chat.

**校验点**:

- Agent list is empty
- No response from Chat

---

#### test_model_switch_and_chat_continuity: test_model_switch_and_chat_continuity

**优先级**: unknown

**测试目的**: Verify Chat continues to work after switching models and that context is preserved.

**校验点**:

- No response to the first message
- No response to recall message (still timed out after retry)
- No response after switching models
- No response after switching back to the original model

---

#### test_security_config_affects_chat: test_security_config_affects_chat

**优先级**: unknown

**测试目的**: Verify the linkage between security guard config and Chat behavior.

**校验点**:

- Chat baseline failure: no response
- Assertion check

---

#### test_workspace_file_and_chat_qa: test_workspace_file_and_chat_qa

**优先级**: unknown

**测试目的**: Verify linkage between workspace files and Chat file Q&A.

**校验点**:

- No response to file Q&A

---

#### test_env_and_runtime_config_consistency: test_env_and_runtime_config_consistency

**优先级**: unknown

**测试目的**: Verify consistency between environment variables and runtime config.

**校验点**:

- Assertion check

---

#### test_agent_switcher_in_chat: test_agent_switcher_in_chat

**优先级**: unknown

**测试目的**: 

---

## DEBUG 模块

用例数：5

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_debug_page_load_and_display | test_debug_page_load_and_display | unknown | Verify Debug page load and basic element display. |  |
| test_debug_log_control_buttons | test_debug_log_control_buttons | unknown | Verify log control button functionality. |  |
| test_debug_log_level_filter | test_debug_log_level_filter | unknown | Verify log level filter functionality. |  |
| test_debug_log_keyword_search | test_debug_log_keyword_search | unknown | Verify log keyword search functionality. |  |
| test_debug_log_file_info | test_debug_log_file_info | unknown | Verify log file info display. |  |

### 详细用例

#### test_debug_page_load_and_display: test_debug_page_load_and_display

**优先级**: unknown

**测试目的**: Verify Debug page load and basic element display.

**校验点**:

- Assertion check

---

#### test_debug_log_control_buttons: test_debug_log_control_buttons

**优先级**: unknown

**测试目的**: Verify log control button functionality.

**校验点**:

- Assertion check
- Auto-refresh toggle state should change
- Sort toggle state should change

---

#### test_debug_log_level_filter: test_debug_log_level_filter

**优先级**: unknown

**测试目的**: Verify log level filter functionality.

---

#### test_debug_log_keyword_search: test_debug_log_keyword_search

**优先级**: unknown

**测试目的**: Verify log keyword search functionality.

---

#### test_debug_log_file_info: test_debug_log_file_info

**优先级**: unknown

**测试目的**: Verify log file info display.

---

## ENVIRONMENTS 模块

用例数：12

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_environment_list_display | test_environment_list_display | P0 | Verify env var list renders correctly. |  |
| test_add_environment_success | test_add_environment_success | P0 | Verify adding an env var succeeds. |  |
| test_add_environment_cancel | test_add_environment_cancel | P0 | Verify cancelling add env var. |  |
| test_add_environment_key_required | test_add_environment_key_required | P0 | Verify Key is required. |  |
| test_edit_environment | test_edit_environment | P0 | Verify editing an env var. |  |
| test_delete_environment | test_delete_environment | P0 | Verify deleting an env var. |  |
| test_env_var_multi_row_and_checkbox | test_env_var_multi_row_and_checkbox | P0 | Verify multi-row add, checkbox and delete. |  |
| test_env_var_save_and_persist | test_env_var_save_and_persist | P0 | Verify env var save and persistence. |  |
| test_env_var_key_format_validation | test_env_var_key_format_validation | P0 | Verify env var Key format validation. |  |
| test_batch_operations | test_batch_operations | P0 | Verify batch ops: add multiple rows -> select all ... |  |
| test_environment_api | test_environment_api | P0 | Verify env var API. |  |
| test_env_key_duplicate_detection | test_env_key_duplicate_detection | P0 | Test env var Key duplicate conflict detection. |  |

### 详细用例

#### test_environment_list_display: test_environment_list_display

**优先级**: P0

**测试目的**: Verify env var list renders correctly.

---

#### test_add_environment_success: test_add_environment_success

**优先级**: P0

**测试目的**: Verify adding an env var succeeds.

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

#### test_add_environment_cancel: test_add_environment_cancel

**优先级**: P0

**测试目的**: Verify cancelling add env var.

**校验点**:

- Assertion check

---

#### test_add_environment_key_required: test_add_environment_key_required

**优先级**: P0

**测试目的**: Verify Key is required.

---

#### test_edit_environment: test_edit_environment

**优先级**: P0

**测试目的**: Verify editing an env var.

**校验点**:

- Assertion check
- Assertion check

---

#### test_delete_environment: test_delete_environment

**优先级**: P0

**测试目的**: Verify deleting an env var.

**校验点**:

- Assertion check

---

#### test_env_var_multi_row_and_checkbox: test_env_var_multi_row_and_checkbox

**优先级**: P0

**测试目的**: Verify multi-row add, checkbox and delete.

**校验点**:

- Assertion check
- First row Key not filled
- Second row Key not filled
- Checkbox should start unchecked
- Checkbox should be checked after check()

---

#### test_env_var_save_and_persist: test_env_var_save_and_persist

**优先级**: P0

**测试目的**: Verify env var save and persistence.

**校验点**:

- Assertion check
- Assertion check
- Assertion check
- Assertion check

---

#### test_env_var_key_format_validation: test_env_var_key_format_validation

**优先级**: P0

**测试目的**: Verify env var Key format validation.

---

#### test_batch_operations: test_batch_operations

**优先级**: P0

**测试目的**: Verify batch ops: add multiple rows -> select all -> batch delete -> verify row count.

**校验点**:

- Assertion check
- Failed to check any checkbox
- Assertion check

---

#### test_environment_api: test_environment_api

**优先级**: P0

**测试目的**: Verify env var API.

**校验点**:

- API response should be a list
- Assertion check
- Assertion check

---

#### test_env_key_duplicate_detection: test_env_key_duplicate_detection

**优先级**: P0

**测试目的**: Test env var Key duplicate conflict detection.

**校验点**:

- Page content should not be empty

---

## FILES 模块

用例数：8

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_file_list_view_edit_save | test_file_list_view_edit_save | P0 | Verify file list display and opening the editor. | Hard-assert breadcrumb / core files heading, Hard-assert file list count > 0, Hard-assert first file name / meta non-empty |
| test_file_toggle_reorder_memory | test_file_toggle_reorder_memory | P0 | Verify file toggle, drag reorder, and reload resto... | Toggle switch -> assert state flipped, Restore -> assert state back to initial, Record the initial file order |
| test_file_content_edit_save_reset | test_file_content_edit_save_reset | P0 | Verify file content edit, save and reset. | Click file to open editor (default Markdown preview mode), Turn off the preview switch to enter edit mode (textarea), Modify content in the textarea |
| test_workspace_download_and_upload_button | test_workspace_download_and_upload_button | P0 | Verify workspace upload and per-file download butt... |  |
| test_daily_memory_view | test_daily_memory_view | P0 | Test daily memory expand/collapse. | Find the daily memory section in the file list, Expand a daily memory entry to view its content, Collapse a daily memory entry |
| test_markdown_preview | test_markdown_preview | P0 | Test Markdown live preview. | Select a Markdown file in the file list, Verify the editor area exists, Verify the preview area exists |
| test_workspace_zip_upload | test_workspace_zip_upload | P0 | Test the workspace upload entry. |  |
| test_workspace_zip_download | test_workspace_zip_download | P0 | Test downloading a workspace file. |  |

### 详细用例

#### test_file_list_view_edit_save: test_file_list_view_edit_save

**优先级**: P0

**测试目的**: Verify file list display and opening the editor.

**校验点**:

- File list should have at least 1 file
- File name is empty
- File meta is empty
- Editor/preview content is empty
- There should be at least 1 enable switch

---

#### test_file_toggle_reorder_memory: test_file_toggle_reorder_memory

**优先级**: P0

**测试目的**: Verify file toggle, drag reorder, and reload restore.

**校验点**:

- Assertion check
- Assertion check
- File list is empty after reload

---

#### test_file_content_edit_save_reset: test_file_content_edit_save_reset

**优先级**: P0

**测试目的**: Verify file content edit, save and reset.

**校验点**:

- Assertion check

---

#### test_workspace_download_and_upload_button: test_workspace_download_and_upload_button

**优先级**: P0

**测试目的**: Verify workspace upload and per-file download buttons.

**校验点**:

- Assertion check
- Upload button should be enabled
- A hidden file upload input should exist
- Download button should be enabled

---

#### test_daily_memory_view: test_daily_memory_view

**优先级**: P0

**测试目的**: Test daily memory expand/collapse.

---

#### test_markdown_preview: test_markdown_preview

**优先级**: P0

**测试目的**: Test Markdown live preview.

---

#### test_workspace_zip_upload: test_workspace_zip_upload

**优先级**: P0

**测试目的**: Test the workspace upload entry.

**校验点**:

- Files page should have an upload button
- A hidden file input should exist

---

#### test_workspace_zip_download: test_workspace_zip_download

**优先级**: P0

**测试目的**: Test downloading a workspace file.

**校验点**:

- Assertion check
- Editor toolbar should have a download button
- Download button should be enabled

---

## HEARTBEAT 模块

用例数：4

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_heartbeat_display_and_toggle | test_heartbeat_display_and_toggle | P0 | Verify page display and enable/disable toggle. |  |
| test_full_heartbeat_configuration | test_full_heartbeat_configuration | P0 | Verify full heartbeat config flow. |  |
| test_target_session_and_active_hours | test_target_session_and_active_hours | P0 | Verify target session selection and active hours c... |  |
| test_heartbeat_interval_unit | test_heartbeat_interval_unit | P0 | Test heartbeat interval unit switching. |  |

### 详细用例

#### test_heartbeat_display_and_toggle: test_heartbeat_display_and_toggle

**优先级**: P0

**测试目的**: Verify page display and enable/disable toggle.

**业务场景**: Admin opens the heartbeat config page, confirms all config items render correctly, then toggles enable/disable and verifies the change took effect.

**测试流程**:

1. Open Heartbeat page, verify title
2. Verify config card and form elements (switch, interval, time, save button)
3. Record current enabled state
4. Toggle state and save
5. Verify state change
6. Restore original state

**校验点**:

- Assertion check

---

#### test_full_heartbeat_configuration: test_full_heartbeat_configuration

**优先级**: P0

**测试目的**: Verify full heartbeat config flow.

**业务场景**: Admin completes full heartbeat config in one go: set interval to 30 minutes, scheduled time to 09:00, choose a skill, enable heartbeat, then save and verify all config items took effect.

**测试流程**:

1. Open Heartbeat page
2. Record original config (enabled state, interval, time)
3. Set interval to 15 minutes
4. Set scheduled time to 09:00
5. Choose a skill (if any available)
6. Enable heartbeat, save config
7. Verify all config took effect
8. Restore original config

---

#### test_target_session_and_active_hours: test_target_session_and_active_hours

**优先级**: P0

**测试目的**: Verify target session selection and active hours config.

**业务场景**: Admin configures heartbeat target session and active hours, verifies that different target session options and active hours config are saved correctly.

**测试流程**:

1. Open Heartbeat page
2. Record original config
3. Find target session selector (main/last)
4. Verify selector exists and record current value
5. Switch target session option
6. Find active hours toggle
7. Enable active hours
8. Set start time
9. Set end time
10. Save config
11. Verify config saved
12. Restore original config

---

#### test_heartbeat_interval_unit: test_heartbeat_interval_unit

**优先级**: P0

**测试目的**: Test heartbeat interval unit switching.

**校验点**:

- Unit dropdown options should not be empty
- Assertion check

---

## INBOX 模块

用例数：7

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_inbox_page_renders_with_seeded_events | test_inbox_page_renders_with_seeded_events | P0 |  |  |
| test_message_card_renders_and_modal_opens | test_message_card_renders_and_modal_opens | P0 |  |  |
| test_batch_mode_select_and_delete | test_batch_mode_select_and_delete | P0 |  |  |
| test_sidebar_unread_dot_appears_with_seeded_event | test_sidebar_unread_dot_appears_with_seeded_event | P0 |  |  |
| test_skill_autosync_notification_card | test_skill_autosync_notification_card | P0 |  |  |
| test_single_card_delete | test_single_card_delete | P0 |  |  |
| test_mark_all_read | test_mark_all_read | P0 |  |  |

### 详细用例

#### test_inbox_page_renders_with_seeded_events: test_inbox_page_renders_with_seeded_events

**优先级**: P0

**测试目的**: 

**校验点**:

- Assertion check

---

#### test_message_card_renders_and_modal_opens: test_message_card_renders_and_modal_opens

**优先级**: P0

**测试目的**: 

---

#### test_batch_mode_select_and_delete: test_batch_mode_select_and_delete

**优先级**: P0

**测试目的**: 

**校验点**:

- Assertion check
- Assertion check

---

#### test_sidebar_unread_dot_appears_with_seeded_event: test_sidebar_unread_dot_appears_with_seeded_event

**优先级**: P0

**测试目的**: 

---

#### test_skill_autosync_notification_card: test_skill_autosync_notification_card

**优先级**: P0

**测试目的**: 

---

#### test_single_card_delete: test_single_card_delete

**优先级**: P0

**测试目的**: 

**校验点**:

- Assertion check

---

#### test_mark_all_read: test_mark_all_read

**优先级**: P0

**测试目的**: 

**校验点**:

- Assertion check

---

## LOGIN 模块

用例数：5

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_auth_status_api | test_auth_status_api | P0 | Verify auth status API. |  |
| test_login_page_accessible | test_login_page_accessible | P0 | Verify login page is accessible. |  |
| test_multi_user_management | test_multi_user_management | P0 | Test multi-user management / permission control. |  |
| test_login_empty_form_validation | test_login_empty_form_validation | P0 | Verify required-field validation when submitting a... |  |
| test_login_partial_form_validation | test_login_partial_form_validation | P0 | Verify validation when only username is filled and... |  |

### 详细用例

#### test_auth_status_api: test_auth_status_api

**优先级**: P0

**测试目的**: Verify auth status API.

**校验点**:

- Auth status API endpoint should exist
- Auth status API should accept GET

---

#### test_login_page_accessible: test_login_page_accessible

**优先级**: P0

**测试目的**: Verify login page is accessible.

**校验点**:

- Login page should load

---

#### test_multi_user_management: test_multi_user_management

**优先级**: P0

**测试目的**: Test multi-user management / permission control.

---

#### test_login_empty_form_validation: test_login_empty_form_validation

**优先级**: P0

**测试目的**: Verify required-field validation when submitting an empty login form.

---

#### test_login_partial_form_validation: test_login_partial_form_validation

**优先级**: P0

**测试目的**: Verify validation when only username is filled and password is empty.

---

## MCP 模块

用例数：5

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_mcp_list_toggle_and_cancel_delete | test_mcp_list_toggle_and_cancel_delete | P0 | Verify MCP client list display and enable/disable ... |  |
| test_create_mcp_client_stdio_and_http | test_create_mcp_client_stdio_and_http | P0 | Verify create dialog open, JSON fill, and cancel c... |  |
| test_create_and_delete_mcp_client | test_create_and_delete_mcp_client | P0 | Verify MCP client creation and deletion flow. |  |
| test_mcp_client_edit | test_mcp_client_edit | P0 | Test MCP client edit configuration. |  |
| test_mcp_multi_protocol | test_mcp_multi_protocol | P0 | Test MCP multi-protocol creation. |  |

### 详细用例

#### test_mcp_list_toggle_and_cancel_delete: test_mcp_list_toggle_and_cancel_delete

**优先级**: P0

**测试目的**: Verify MCP client list display and enable/disable toggle.

**校验点**:

- Create client button should not be disabled
- Should have at least 1 MCP client
- MCP client title is empty
- Assertion check
- Assertion check

---

#### test_create_mcp_client_stdio_and_http: test_create_mcp_client_stdio_and_http

**优先级**: P0

**测试目的**: Verify create dialog open, JSON fill, and cancel close.

**校验点**:

- Assertion check
- Assertion check
- stdio config was not filled correctly
- stdio config missing command
- HTTP config was not filled correctly

---

#### test_create_and_delete_mcp_client: test_create_and_delete_mcp_client

**优先级**: P0

**测试目的**: Verify MCP client creation and deletion flow.

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

#### test_mcp_client_edit: test_mcp_client_edit

**优先级**: P0

**测试目的**: Test MCP client edit configuration.

**校验点**:

- Modal content too short
- JSON edit area content is empty
- Editor should be editable
- Code editor should be visible

---

#### test_mcp_multi_protocol: test_mcp_multi_protocol

**优先级**: P0

**测试目的**: Test MCP multi-protocol creation.

**校验点**:

- Create MCP client button not found
- JSON input does not contain stdio config

---

## MEMORY 模块

用例数：7

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_memory_card_ui_renders | test_memory_card_ui_renders | P1 |  |  |
| test_workspace_memory_md_visible | test_workspace_memory_md_visible | P1 |  |  |
| test_memory_search_recall_seeded | test_memory_search_recall_seeded | P1 |  |  |
| test_auto_memory_interval_persistence | test_auto_memory_interval_persistence | P1 |  |  |
| test_dream_cron_persistence | test_dream_cron_persistence | P1 |  |  |
| test_memory_backend_select_switches_tabs | test_memory_backend_select_switches_tabs | P1 |  |  |
| test_auto_memory_search_toggle_and_max_results | test_auto_memory_search_toggle_and_max_results | P1 |  |  |

### 详细用例

#### test_memory_card_ui_renders: test_memory_card_ui_renders

**优先级**: P1

**测试目的**: 

---

#### test_workspace_memory_md_visible: test_workspace_memory_md_visible

**优先级**: P1

**测试目的**: 

**校验点**:

- Assertion check

---

#### test_memory_search_recall_seeded: test_memory_search_recall_seeded

**优先级**: P1

**测试目的**: 

---

#### test_auto_memory_interval_persistence: test_auto_memory_interval_persistence

**优先级**: P1

**测试目的**: 

**校验点**:

- Assertion check

---

#### test_dream_cron_persistence: test_dream_cron_persistence

**优先级**: P1

**测试目的**: 

**校验点**:

- Assertion check

---

#### test_memory_backend_select_switches_tabs: test_memory_backend_select_switches_tabs

**优先级**: P1

**测试目的**: 

**校验点**:

- Assertion check
- Assertion check

---

#### test_auto_memory_search_toggle_and_max_results: test_auto_memory_search_toggle_and_max_results

**优先级**: P1

**测试目的**: 

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

## MODELS 模块

用例数：10

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_model_list_display | test_model_list_display | P0 | Verify local models list renders and empty state i... |  |
| test_model_download_flow | test_model_download_flow | P0 | Verify model download flow: open the local Provide... |  |
| test_model_serve_flow | test_model_serve_flow | P0 | Verify model start-service flow. |  |
| test_model_management_operations | test_model_management_operations | P0 | Verify model management operations (delete / stop ... |  |
| test_custom_provider_create_and_delete | test_custom_provider_create_and_delete | P0 | Test the full create-and-delete flow for a custom ... |  |
| test_provider_config_and_connection_test | test_provider_config_and_connection_test | P0 | Test provider config and connection test. |  |
| test_provider_search_filter | test_provider_search_filter | P0 | Test the Provider search filter. |  |
| test_model_activation | test_model_activation | P0 | Test model activation and management. |  |
| test_openrouter_filter | test_openrouter_filter | P0 | Test OpenRouter filter configuration. |  |
| test_model_json_editor | test_model_json_editor | P0 | Test the model JSON config editor. |  |

### 详细用例

#### test_model_list_display: test_model_list_display

**优先级**: P0

**测试目的**: Verify local models list renders and empty state is handled.

**校验点**:

- Models page should render provider tiles or known provider names; saw neither
- Models page should render at least one Provider card
- Page should display empty state or model list
- Provider modal content should not be empty

---

#### test_model_download_flow: test_model_download_flow

**优先级**: P0

**测试目的**: Verify model download flow: open the local Provider manage modal, verify download-related UI.

**校验点**:

- Models page did not load
- Provider section not found

---

#### test_model_serve_flow: test_model_serve_flow

**优先级**: P0

**测试目的**: Verify model start-service flow.

**校验点**:

- Model service page should have at least one of: port info, service status, or start button

---

#### test_model_management_operations: test_model_management_operations

**优先级**: P0

**测试目的**: Verify model management operations (delete / stop service).

---

#### test_custom_provider_create_and_delete: test_custom_provider_create_and_delete

**优先级**: P0

**测试目的**: Test the full create-and-delete flow for a custom model provider.

**校验点**:

- Modal did not close after creating provider; creation may have failed
- Assertion check
- Assertion check
- Assertion check

---

#### test_provider_config_and_connection_test: test_provider_config_and_connection_test

**优先级**: P0

**测试目的**: Test provider config and connection test.

**校验点**:

- Assertion check

---

#### test_provider_search_filter: test_provider_search_filter

**优先级**: P0

**测试目的**: Test the Provider search filter.

**校验点**:

- No Provider cards on the page
- Assertion check
- Assertion check

---

#### test_model_activation: test_model_activation

**优先级**: P0

**测试目的**: Test model activation and management.

**校验点**:

- No Provider cards on the page
- Model management modal is empty

---

#### test_openrouter_filter: test_openrouter_filter

**优先级**: P0

**测试目的**: Test OpenRouter filter configuration.

---

#### test_model_json_editor: test_model_json_editor

**优先级**: P0

**测试目的**: Test the model JSON config editor.

---

## PLUGINS 模块

用例数：3

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_plugin_manager_page_loads | test_plugin_manager_page_loads | P0 |  |  |
| test_market_compat_tags_render | test_market_compat_tags_render | P0 |  |  |
| test_incompatible_install_warning_modal | test_incompatible_install_warning_modal | P0 |  |  |

### 详细用例

#### test_plugin_manager_page_loads: test_plugin_manager_page_loads

**优先级**: P0

**测试目的**: 

---

#### test_market_compat_tags_render: test_market_compat_tags_render

**优先级**: P0

**测试目的**: 

**校验点**:

- Assertion check
- Assertion check

---

#### test_incompatible_install_warning_modal: test_incompatible_install_warning_modal

**优先级**: P0

**测试目的**: 

---

## RUNTIME_CONFIG 模块

用例数：10

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_react_agent_language_and_timezone | test_react_agent_language_and_timezone | P0 | Verify ReAct agent language switching and timezone... | Runtime config page navigation and load, ReAct agent tab active by default, Agent language dropdown display and switching |
| test_agent_config_tab_switch | test_agent_config_tab_switch | P0 | Verify tab switching and content display on the ru... | Switch to LLM auto-retry tab and verify content, Switch to LLM rate limiter tab and verify content, Switch to context compaction tab and verify content |
| test_config_save_and_reset | test_config_save_and_reset | P0 | Verify config modification, saving and persistence... | Visit the runtime config page, Switch to the context compaction tab, Locate the enable switch and record its current state |
| test_llm_retry_config | test_llm_retry_config | P0 | LLM retry configuration test. | Switch to LLM auto-retry tab, Retry switch display and toggle, Display and edit max retries, backoff base, backoff cap |
| test_llm_rate_limiter_config | test_llm_rate_limiter_config | P0 | LLM rate limiter configuration test. | Switch to LLM rate limiter tab, Display of max concurrency, QPM, pause, jitter, acquire timeout fields, Verify config modification and save |
| test_tool_result_compact_config | test_tool_result_compact_config | P0 | Context management config test (tool-result compac... | Switch to the context management tab, Verify panel content (context compaction, tool result compaction, etc.), Verify config items are displayed |
| test_embedding_config | test_embedding_config | P0 | Long-term memory config test (embedding config was... | Switch to the long-term memory tab, Verify panel content (vector model config, memory toggle, etc.), Verify toggles and config items are displayed |
| test_context_compact_config | test_context_compact_config | P0 | Test the display and editing of context compaction... | Switch to the Context Compact tab, Verify form fields exist (switches, sliders, etc.), Modify config and save |
| test_config_dynamic_linkage | test_config_dynamic_linkage | P0 | Test dynamic linkage between config items. |  |
| test_memory_summary_config | test_memory_summary_config | P0 | Test the display and editing of memory summary con... | Switch to the Memory Summary tab, Verify form fields exist (switches, inputs, sliders, etc.), Modify config and verify |

### 详细用例

#### test_react_agent_language_and_timezone: test_react_agent_language_and_timezone

**优先级**: P0

**测试目的**: Verify ReAct agent language switching and timezone configuration.

**校验点**:

- Assertion check
- Assertion check
- Timezone value is empty
- Assertion check
- Assertion check

---

#### test_agent_config_tab_switch: test_agent_config_tab_switch

**优先级**: P0

**测试目的**: Verify tab switching and content display on the runtime config page.

**校验点**:

- No config items in LLM auto-retry tab
- No config items in LLM rate limiter tab
- No config items in context management tab

---

#### test_config_save_and_reset: test_config_save_and_reset

**优先级**: P0

**测试目的**: Verify config modification, saving and persistence.

**校验点**:

- Assertion check
- Assertion check
- Assertion check
- Assertion check

---

#### test_llm_retry_config: test_llm_retry_config

**优先级**: P0

**测试目的**: LLM retry configuration test.

**校验点**:

- Assertion check
- Assertion check

---

#### test_llm_rate_limiter_config: test_llm_rate_limiter_config

**优先级**: P0

**测试目的**: LLM rate limiter configuration test.

**校验点**:

- Assertion check
- Assertion check

---

#### test_tool_result_compact_config: test_tool_result_compact_config

**优先级**: P0

**测试目的**: Context management config test (tool-result compaction was merged here).

**校验点**:

- Assertion check
- Assertion check

---

#### test_embedding_config: test_embedding_config

**优先级**: P0

**测试目的**: Long-term memory config test (embedding config was merged here).

**校验点**:

- Assertion check
- Assertion check

---

#### test_context_compact_config: test_context_compact_config

**优先级**: P0

**测试目的**: Test the display and editing of context compaction config.

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

#### test_config_dynamic_linkage: test_config_dynamic_linkage

**优先级**: P0

**测试目的**: Test dynamic linkage between config items.

**校验点**:

- Assertion check
- Assertion check

---

#### test_memory_summary_config: test_memory_summary_config

**优先级**: P0

**测试目的**: Test the display and editing of memory summary config.

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

## SECURITY 模块

用例数：8

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_tool_guard_toggle_and_tab_switch | test_tool_guard_toggle_and_tab_switch | P0 | Verify Tool Guard switch toggling and tab switchin... | Security page access and load, Tool Guard tab shown by default, Tool Guard enable switch toggle (on -> off -> on) |
| test_file_guard_path_add_and_tool_select | test_file_guard_path_add_and_tool_select | P0 | Verify File Guard path add and Tool Guard dropdown... | File Guard path input and add, Add-button state verification (disabled on empty input), Switch back to Tool Guard tab |
| test_security_config_save_and_persist | test_security_config_save_and_persist | P0 | Verify Security config save and persistence. | Open the Security page, Record the current Tool Guard switch state, Toggle the Tool Guard switch |
| test_security_rule_crud | test_security_rule_crud | P0 | Verify security rule CRUD. | Open the Security page and switch to the Tool Guard tab, Add a Tool Guard rule (rule ID, regex pattern, severity, etc.), Verify the rule appears in the rules table |
| test_skill_scanner_mode_switch | test_skill_scanner_mode_switch | P0 | Verify Skill Scanner mode switching. | Open the Security page, Switch to the Skill Scanner tab, Verify the mode selector exists |
| test_denied_tools_config | test_denied_tools_config | P0 | Test the denied tools list configuration. | Find the denied tools list in the Tool Guard tab, Add a tool to the denied list, Verify the tool was added |
| test_rule_preview | test_rule_preview | P0 | Test the security rule preview. | Find the rules table in Tool Guard, Click the preview button, Verify the preview modal shows |
| test_security_batch_rule_toggle | test_security_batch_rule_toggle | P0 | Test batch enabling/disabling of security rules. |  |

### 详细用例

#### test_tool_guard_toggle_and_tab_switch: test_tool_guard_toggle_and_tab_switch

**优先级**: P0

**测试目的**: Verify Tool Guard switch toggling and tab switching.

**校验点**:

- Switch toggle did not take effect
- Switch did not revert to initial state

---

#### test_file_guard_path_add_and_tool_select: test_file_guard_path_add_and_tool_select

**优先级**: P0

**测试目的**: Verify File Guard path add and Tool Guard dropdown interaction.

**校验点**:

- Assertion check
- Assertion check
- Protected-tools dropdown options are empty
- First option text is empty

---

#### test_security_config_save_and_persist: test_security_config_save_and_persist

**优先级**: P0

**测试目的**: Verify Security config save and persistence.

**校验点**:

- Assertion check
- Assertion check
- Assertion check
- Skill Scanner tab content is empty
- Assertion check

---

#### test_security_rule_crud: test_security_rule_crud

**优先级**: P0

**测试目的**: Verify security rule CRUD.

**校验点**:

- Rule row should contain a severity tag
- Rule switch did not toggle
- Assertion check

---

#### test_skill_scanner_mode_switch: test_skill_scanner_mode_switch

**优先级**: P0

**测试目的**: Verify Skill Scanner mode switching.

**校验点**:

- Assertion check
- Assertion check
- Assertion check

---

#### test_denied_tools_config: test_denied_tools_config

**优先级**: P0

**测试目的**: Test the denied tools list configuration.

**校验点**:

- Assertion check
- No selected tool tags found

---

#### test_rule_preview: test_rule_preview

**优先级**: P0

**测试目的**: Test the security rule preview.

**校验点**:

- Preview modal content is empty

---

#### test_security_batch_rule_toggle: test_security_batch_rule_toggle

**优先级**: P0

**测试目的**: Test batch enabling/disabling of security rules.

---

## SESSIONS 模块

用例数：5

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_session_list_filter_and_detail | test_session_list_filter_and_detail | P0 | Verify session list display, filtering, sorting an... |  |
| test_edit_and_delete_session | test_edit_and_delete_session | P0 | Verify edit, delete and batch-delete features. |  |
| test_session_edit_name_and_save | test_session_edit_name_and_save | P0 | Verify session name edit-and-save flow. | Click the edit button to open the edit drawer, Verify the edit drawer opens, Modify the session name |
| test_session_batch_delete | test_session_batch_delete | P0 | Verify batch delete sessions. | Tick checkboxes for multiple sessions, Verify the batch-delete button becomes available, Click the batch-delete button |
| test_session_filter_by_userid_and_channel | test_session_filter_by_userid_and_channel | P0 | Test combined session filter by UserID and Channel... | Filter by UserID input, Filter by Channel dropdown, Verify combined filter results |

### 详细用例

#### test_session_list_filter_and_detail: test_session_list_filter_and_detail

**优先级**: P0

**测试目的**: Verify session list display, filtering, sorting and detail view.

**测试流程**:

1. Visit the Sessions page and verify the table loads
2. Verify key columns (ID / UserID / Channel / Created)
3. Verify filters are available (UserID / Channel)
4. Verify sorting (table header is clickable)
5. View detail for the first session

**校验点**:

- Assertion check
- Table headers should exist
- Assertion check
- Visible session rows should exist
- Session detail content should not be empty

---

#### test_edit_and_delete_session: test_edit_and_delete_session

**优先级**: P0

**测试目的**: Verify edit, delete and batch-delete features.

**测试流程**:

1. Visit the Sessions page
2. Verify operable sessions exist
3. Click the edit button and verify the dialog opens
4. Cancel editing and verify the dialog closes
5. Verify the delete button is available
6. Verify batch selection and batch-delete

**校验点**:

- ensure_session_data fixture should have created test data, but the page shows 0 sessions
- Assertion check
- No delete button found on the page
- First delete button should be enabled
- No row checkboxes found (batch selection should be available)

---

#### test_session_edit_name_and_save: test_session_edit_name_and_save

**优先级**: P0

**测试目的**: Verify session name edit-and-save flow.

**测试流程**:

1. Visit the Sessions page
2. Verify operable sessions exist
3. Click the edit button on the first session
4. Verify the edit drawer opens
5. Change the session name to "E2E_Test_Renamed_xxx"
6. Click save
7. Verify the drawer closes
8. Verify the new name appears in the list
9. Restore the original name (edit and save again)

**校验点**:

- Assertion check

---

#### test_session_batch_delete: test_session_batch_delete

**优先级**: P0

**测试目的**: Verify batch delete sessions.

**测试流程**:

1. Visit the Sessions page
2. Verify at least 2 sessions exist
3. Tick checkboxes for the first two sessions
4. Verify the batch-delete button becomes available
5. Click the batch-delete button
6. Confirm deletion (if a confirm dialog appears)
7. Verify the session count decreased

**校验点**:

- At least 1 session checkbox should be ticked
- Batch-delete button not found
- Assertion check

---

#### test_session_filter_by_userid_and_channel: test_session_filter_by_userid_and_channel

**优先级**: P0

**测试目的**: Test combined session filter by UserID and Channel.

**校验点**:

- No filter controls found (UserID input or Channel selector)
- ensure_session_data fixture should have created test data, but session list is still empty
- Session row has too few columns
- Could not extract UserID
- Assertion check

---

## SKILL_POOL 模块

用例数：9

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_skill_pool_page_load | test_skill_pool_page_load | P0 | Verify skill pool page loads normally. |  |
| test_skill_pool_search | test_skill_pool_search | P0 | Test skill pool search/filter functionality. |  |
| test_skill_pool_install | test_skill_pool_install | P0 | Test installing a skill to an agent. |  |
| test_skill_pool_broadcast | test_skill_pool_broadcast | P0 | Test broadcasting skill to multiple agents. |  |
| test_skill_pool_batch_delete | test_skill_pool_batch_delete | P0 | Test skill pool batch delete functionality. |  |
| test_skill_pool_zip_import | test_skill_pool_zip_import | P0 | Test skill pool ZIP import (with actual upload). |  |
| test_skill_pool_builtin_import | test_skill_pool_builtin_import | P0 | Test importing the builtin skill pack. |  |
| test_skill_card_sync_badge_and_button | test_skill_card_sync_badge_and_button | P0 |  |  |
| test_auto_sync_switch_reveals_targets_and_persists | test_auto_sync_switch_reveals_targets_and_persists | P0 |  |  |

### 详细用例

#### test_skill_pool_page_load: test_skill_pool_page_load

**优先级**: P0

**测试目的**: Verify skill pool page loads normally.

**校验点**:

- Page should load

---

#### test_skill_pool_search: test_skill_pool_search

**优先级**: P0

**测试目的**: Test skill pool search/filter functionality.

**校验点**:

- Assertion check

---

#### test_skill_pool_install: test_skill_pool_install

**优先级**: P0

**测试目的**: Test installing a skill to an agent.

**校验点**:

- Broadcast Modal content is empty
- Broadcast Modal should have selectable elements (pickerCard/checkbox/select/list item)
- Confirm button should exist in broadcast Modal

---

#### test_skill_pool_broadcast: test_skill_pool_broadcast

**优先级**: P0

**测试目的**: Test broadcasting skill to multiple agents.

**校验点**:

- Broadcast Modal should have workspace/selection items
- Confirm button not found in broadcast Modal
- Confirm button should be enabled after selecting workspaces

---

#### test_skill_pool_batch_delete: test_skill_pool_batch_delete

**优先级**: P0

**测试目的**: Test skill pool batch delete functionality.

**校验点**:

- Checkboxes should appear in batch mode
- Delete button should be enabled after selecting a skill

---

#### test_skill_pool_zip_import: test_skill_pool_zip_import

**优先级**: P0

**测试目的**: Test skill pool ZIP import (with actual upload).

**校验点**:

- Hidden ZIP file input not found
- Assertion check

---

#### test_skill_pool_builtin_import: test_skill_pool_builtin_import

**优先级**: P0

**测试目的**: Test importing the builtin skill pack.

---

#### test_skill_card_sync_badge_and_button: test_skill_card_sync_badge_and_button

**优先级**: P0

**测试目的**: 

**校验点**:

- Failed to seed pool skill
- Assertion check

---

#### test_auto_sync_switch_reveals_targets_and_persists: test_auto_sync_switch_reveals_targets_and_persists

**优先级**: P0

**测试目的**: 

**校验点**:

- Failed to seed pool skill
- Target-agent select should be hidden while Auto Sync is off
- Card missing after save

---

## SKILLS 模块

用例数：8

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_skill_list_filter_and_search | test_skill_list_filter_and_search | P0 | Verify skill list display, card info and search fi... |  |
| test_import_toggle_delete_and_batch | test_import_toggle_delete_and_batch | P0 | Verify action buttons, enable/disable toggle and b... |  |
| test_skill_create_edit_delete | test_skill_create_edit_delete | P0 | Verify the full skill create/edit/delete lifecycle... |  |
| test_skill_tag_management_and_filter | test_skill_tag_management_and_filter | P0 | Test skill tag management and filter. |  |
| test_skill_view_toggle | test_skill_view_toggle | P0 | Test skill view toggle. |  |
| test_skill_import_from_hub | test_skill_import_from_hub | P0 | Test importing a skill from Hub. |  |
| test_skill_pool_sync | test_skill_pool_sync | P0 | Test skill pool upload/download sync. |  |
| test_skill_upload_via_zip | test_skill_upload_via_zip | P0 | Verify the full flow of uploading a skill via zip. |  |

### 详细用例

#### test_skill_list_filter_and_search: test_skill_list_filter_and_search

**优先级**: P0

**测试目的**: Verify skill list display, card info and search filter.

**校验点**:

- Skill list should have at least 1 card
- Skill title is empty
- Assertion check
- Description is empty
- Filtered count should not increase

---

#### test_import_toggle_delete_and_batch: test_import_toggle_delete_and_batch

**优先级**: P0

**测试目的**: Verify action buttons, enable/disable toggle and batch operations.

**校验点**:

- Skill list should have at least 1 card
- Add Skill button should not be disabled
- Assertion check
- Assertion check
- Assertion check

---

#### test_skill_create_edit_delete: test_skill_create_edit_delete

**优先级**: P0

**测试目的**: Verify the full skill create/edit/delete lifecycle.

---

#### test_skill_tag_management_and_filter: test_skill_tag_management_and_filter

**优先级**: P0

**测试目的**: Test skill tag management and filter.

**校验点**:

- No skill cards found; page may not have loaded correctly
- Assertion check
- Edit modal did not open
- No form fields found in edit modal
- Tag text should not be empty

---

#### test_skill_view_toggle: test_skill_view_toggle

**优先级**: P0

**测试目的**: Test skill view toggle.

**校验点**:

- View toggle buttons not found

---

#### test_skill_import_from_hub: test_skill_import_from_hub

**优先级**: P0

**测试目的**: Test importing a skill from Hub.

**校验点**:

- Hub import button not found
- URL input not found in import modal
- Confirm button not found in import modal

---

#### test_skill_pool_sync: test_skill_pool_sync

**优先级**: P0

**测试目的**: Test skill pool upload/download sync.

**校验点**:

- Skill pool sync button not found (upload or download)
- Sync modal is empty

---

#### test_skill_upload_via_zip: test_skill_upload_via_zip

**优先级**: P0

**测试目的**: Verify the full flow of uploading a skill via zip.

---

## SMOKE_INFRASTRUCTURE 模块

用例数：4

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_mock_auth_status_intercepted | test_mock_auth_status_intercepted | unknown | Verify /api/auth/status route mock intercepts brow... |  |
| test_mock_agents_list_intercepted | test_mock_agents_list_intercepted | unknown | Verify /api/agents route mock intercepts browser r... |  |
| test_mock_catchall_intercepted | test_mock_catchall_intercepted | unknown | Verify unmatched /api/ routes return empty JSON (c... |  |
| test_login_page_loads | test_login_page_loads | unknown | Navigate to app and verify page renders. |  |

### 详细用例

#### test_mock_auth_status_intercepted: test_mock_auth_status_intercepted

**优先级**: unknown

**测试目的**: Verify /api/auth/status route mock intercepts browser requests.

**校验点**:

- Assertion check
- Assertion check

---

#### test_mock_agents_list_intercepted: test_mock_agents_list_intercepted

**优先级**: unknown

**测试目的**: Verify /api/agents route mock intercepts browser requests.

**校验点**:

- Assertion check
- Assertion check

---

#### test_mock_catchall_intercepted: test_mock_catchall_intercepted

**优先级**: unknown

**测试目的**: Verify unmatched /api/ routes return empty JSON (catch-all).

**校验点**:

- Assertion check

---

#### test_login_page_loads: test_login_page_loads

**优先级**: unknown

**测试目的**: Navigate to app and verify page renders.

**校验点**:

- Assertion check
- Assertion check

---

## TOKEN_USAGE 模块

用例数：5

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_token_usage_overview | test_token_usage_overview | P0 | Verify Token usage overview displays correctly alo... |  |
| test_token_usage_by_model | test_token_usage_by_model | P0 | Test Token usage statistics by model. |  |
| test_token_usage_by_date | test_token_usage_by_date | P0 | Test Token usage trend by date. |  |
| test_token_usage_date_filter | test_token_usage_date_filter | P0 | Test date range filter functionality. |  |
| test_token_usage_empty_state | test_token_usage_empty_state | P0 | Test empty data / loading state display. |  |

### 详细用例

#### test_token_usage_overview: test_token_usage_overview

**优先级**: P0

**测试目的**: Verify Token usage overview displays correctly along with empty state.

**校验点**:

- Token Usage page should display data table or empty state

---

#### test_token_usage_by_model: test_token_usage_by_model

**优先级**: P0

**测试目的**: Test Token usage statistics by model.

**校验点**:

- Table has no column headers
- By-model statistics table should have data rows or show empty state

---

#### test_token_usage_by_date: test_token_usage_by_date

**优先级**: P0

**测试目的**: Test Token usage trend by date.

---

#### test_token_usage_date_filter: test_token_usage_date_filter

**优先级**: P0

**测试目的**: Test date range filter functionality.

**校验点**:

- Date value should not be empty after selecting

---

#### test_token_usage_empty_state: test_token_usage_empty_state

**优先级**: P0

**测试目的**: Test empty data / loading state display.

---

## TOOLS 模块

用例数：4

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_tools_page_display_and_global_toggle | test_tools_page_display_and_global_toggle | P0 | Verify built-in tools page display and global togg... | Navigate to and load /tools page, Breadcrumb verification (Workspace / Built-in Tools), Global enable/disable switch display and toggling |
| test_tool_enable_disable_and_async_toggle | test_tool_enable_disable_and_async_toggle | P0 | Verify per-tool enable/disable and async-execute t... | Per-tool enable/disable button, Async-execute switch toggle, State change verification |
| test_global_toggle_consistency | test_global_toggle_consistency | P0 | Verify the consistency between the global toggle a... | Visit the built-in tools page, Record the initial state of all tool cards, If the global toggle is enabled, disable it first |
| test_tool_async_switch | test_tool_async_switch | P0 | Test the tool async-execute toggle. |  |

### 详细用例

#### test_tools_page_display_and_global_toggle: test_tools_page_display_and_global_toggle

**优先级**: P0

**测试目的**: Verify built-in tools page display and global toggle.

**校验点**:

- Global toggle switch should be visible
- There should be at least one tool card
- Assertion check
- Assertion check
- Breadcrumb should contain Workspace

---

#### test_tool_enable_disable_and_async_toggle: test_tool_enable_disable_and_async_toggle

**优先级**: P0

**测试目的**: Verify per-tool enable/disable and async-execute toggle.

**校验点**:

- Assertion check
- There should be at least one toggle button
- Async-execute state should have toggled
- Async-execute state should be restored
- Assertion check

---

#### test_global_toggle_consistency: test_global_toggle_consistency

**优先级**: P0

**测试目的**: Verify the consistency between the global toggle and all tool card states.

**校验点**:

- There should be at least one tool card
- Global toggle did not enable
- Not all tool cards are 'Enabled'
- Global toggle did not disable

---

#### test_tool_async_switch: test_tool_async_switch

**优先级**: P0

**测试目的**: Test the tool async-execute toggle.

**校验点**:

- Tools page should have toggle controls
- Toggle should have an aria-checked attribute
- Assertion check
- Assertion check

---

## VOICE 模块

用例数：4

| 编号 | 用例名 | 优先级 | 测试目的 | 覆盖点 |
|------|--------|--------|----------|--------|
| test_voice_config_display | test_voice_config_display | P0 | Verify voice transcription config displays correct... |  |
| test_voice_service_toggle | test_voice_service_toggle | P0 | Verify voice service toggle. |  |
| test_twilio_config_form | test_twilio_config_form | P0 | Verify Twilio config form, including input validat... |  |
| test_voice_mode_switch | test_voice_mode_switch | P0 | Test audio mode switching and Whisper status detec... |  |

### 详细用例

#### test_voice_config_display: test_voice_config_display

**优先级**: P0

**测试目的**: Verify voice transcription config displays correctly, including help info and hints.

**校验点**:

- Voice config page should contain voice-related content
- Voice page should have at least one interactable config control
- Voice page should have at least one form field
- Assertion check
- Save button should be enabled

---

#### test_voice_service_toggle: test_voice_service_toggle

**优先级**: P0

**测试目的**: Verify voice service toggle.

**校验点**:

- Assertion check
- Should successfully switch to another option
- Checked option should have changed
- Switch state should change
- No voice service config control found (Radio/Switch/Card/Select/Input)

---

#### test_twilio_config_form: test_twilio_config_form

**优先级**: P0

**测试目的**: Verify Twilio config form, including input validation and required-field markers.

**校验点**:

- Voice config page should contain Twilio or voice-related content
- Assertion check
- Voice config page should have at least one visible config control (input or select)
- Save button should be enabled
- Webhook URL should not be empty

---

#### test_voice_mode_switch: test_voice_mode_switch

**优先级**: P0

**测试目的**: Test audio mode switching and Whisper status detection.

**校验点**:

- Voice config page should have config controls

---
