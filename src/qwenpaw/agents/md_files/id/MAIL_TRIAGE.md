# MAIL_TRIAGE.md — Email Triage Tree

## Usage
- Whenever a new email wakes the agent, read this file in full and match the email against the “Matching Criteria” from top to bottom.
- If one or more leaf rules match, follow the specified “Prerequisite Toolchain → Final Action.” For compound scenarios, follow the combination rules.
- If no rule matches, confidence is low, or the action is irreversible, enter F1 Exploration Mode. First attempt to handle the request through step-by-step approval. Ask the user for guidance only when no viable solution exists or approval has been denied repeatedly.
- Leaf format: Matching Criteria / Prerequisite Toolchain / Final Action / Source.

## A In-Mailbox State Operations (Output: Mailbox State Changes)
- **A1 Mark as Read Silently**
  - Matching Criteria: Marketing or promotional emails, messages from no-reply senders, and notifications that require no follow-up
  - Prerequisite Toolchain: None
  - Final Action: Use `mark_messages` to mark the message as `read`
  - Source: v0.2.0 seed
- **A2 Archive and Categorize**
  - Matching Criteria: Messages worth retaining that do not require a reply, such as billing notices and subscription confirmations
  - Prerequisite Toolchain: (`create_folder` if needed) + `list_folders`
  - Final Action: Use `move_message` to move the message to the appropriate folder
  - Source: v0.2.0 seed
- **A3 Flag for Follow-Up**
  - Matching Criteria: Messages that require the user’s personal attention but cannot currently be handled on the user’s behalf
  - Prerequisite Toolchain: Use `get_message` to verify the content
  - Final Action: Use `mark_messages` to mark the message as `flagged`; for thread-based conversations, use `update_thread` to add an appropriate label
  - Source: v0.2.0 seed
- **A4 Quarantine Spam**
  - Matching Criteria: Obvious spam, phishing, or scam messages
  - Prerequisite Toolchain: None
  - Final Action: Use `move_message` to move the message to the spam or junk folder. Move only; never delete. Calling `delete_message` is strictly prohibited.
  - Source: v0.2.0 seed

## B Information Extraction and Recordkeeping (Output: Workspace Files)
- **B1 Record in Ledger**
  - Matching Criteria: Bills, invoices, receipts, charge notifications, and similar transactional emails containing an amount and date
  - Prerequisite Toolchain: Use `get_message` to extract the amount, date, and purpose
  - Final Action: Use `edit_file` to append a record to the appropriate ledger file
  - Source: v0.2.0 seed
- **B2 Archive Attachments**
  - Matching Criteria: Messages containing non-promotional attachments that should be retained, such as contracts, résumés, reports, or PDF receipts
  - Prerequisite Toolchain: Use `get_message` to verify the attachment list
  - Final Action: Use `get_attachment` to save each attachment to the appropriate category directory in the workspace
  - Source: v0.2.0 seed
- **B3 Add Contact**
  - Matching Criteria: A valid new contact appears who is not already listed in `CONTACTS.md`
  - Prerequisite Toolchain: Use `read_file` to check `CONTACTS.md`
  - Final Action: Use `edit_file` to append the new contact to `CONTACTS.md`
  - Source: v0.2.0 seed

## C Time-Sensitive Actions (Output: Cron Jobs or Calendar Events)
- **C1 Notification Reminder**
  - Matching Criteria: Meeting invitations, interview notices, deadline reminders, and similar time-sensitive notifications
  - Prerequisite Toolchain: Use `get_message` to extract the time and location; use `get_current_time` to determine the appropriate reminder time
  - Final Action: If a Computer Use tool or skill is available, attempt to create an event in the computer’s calendar. Otherwise, use the `cron` skill to create a reminder with `--schedule-type scheduled --type text`
  - Source: v0.2.0 seed
- **C2 Schedule Planning**
  - Matching Criteria: Job applications or résumé submissions, availability inquiries, and other tasks that require arranging time independently
  - Prerequisite Toolchain: Use `get_message` to verify the details, then use an appropriate tool or `cron` to retrieve the current calendar and identify a suitable available time
  - Final Action: If a Computer Use tool or skill is available, attempt to create an event in the computer’s calendar. Otherwise, create a `cron` reminder
  - Source: v0.2.0 seed
- **C3 Travel Itinerary and Reminder**
  - Matching Criteria: Booking confirmations or changes for flights, hotels, trains, and other travel arrangements
  - Prerequisite Toolchain: Use `get_message` to extract the itinerary details
  - Final Action: Use `write_file` to create or update the itinerary. If a Computer Use tool or skill is available, attempt to create an event in the computer’s calendar; otherwise, use `cron` to create or update a pre-departure reminder
  - Source: v0.2.0 seed
- **C4 Shipment Tracking**
  - Matching Criteria: E-commerce orders, shipping notifications, and logistics updates
  - Prerequisite Toolchain: Use `get_message` to extract the carrier and tracking number, or the e-commerce order number. In a browser, sign in to the relevant official website with the email account and look up the shipment or order status
  - Final Action: If a Computer Use tool or skill is available, attempt to create an event in the computer’s calendar. Otherwise, use `cron` to create a `--type agent` task that checks the shipment status daily, notifies the user when the shipment arrives, and then deletes the cron task
  - Source: v0.2.0 seed

## D Outbound Communications (Output: Sent Email)
- **D1 Direct Reply**
  - Matching Criteria: A straightforward inquiry that can be answered using known information
  - Prerequisite Toolchain: Use `read_file` to check `CONTACTS.md` and confirm the sender’s background
  - Final Action: Use `reply_message` to reply to the original sender
  - Source: v0.2.0 seed
- **D2 Continue an Existing Thread**
  - Matching Criteria: A new message in an existing correspondence thread
  - Prerequisite Toolchain: Use `get_thread` to review the conversation context
  - Final Action: Use `reply_message` to respond, then use `update_thread` to update the thread’s labels or status
  - Source: v0.2.0 seed
- **D3 Forward to the Appropriate Contact**
  - Matching Criteria: A message that should be handled by another known contact listed in `CONTACTS.md`
  - Prerequisite Toolchain: Use `read_file` to check `CONTACTS.md` and identify the appropriate recipient
  - Final Action: Use `forward_message` to forward the message with an explanatory note
  - Source: v0.2.0 seed
- **D4 Send a New Email on the User’s Behalf**
  - Matching Criteria: An incoming message requests that a new email be sent to a third party, who must already be listed in `CONTACTS.md`
  - Prerequisite Toolchain: Use `read_file` to check `CONTACTS.md` and verify the recipient
  - Final Action: Use `send_message` to send a new email
  - Source: v0.2.0 seed

## E External Execution (Output: Reported Processing Result)
- **E1 Extract and Report a Verification Code**
  - Matching Criteria: Messages containing a verification code or one-time login code
  - Prerequisite Toolchain: Use `get_message` to extract the code
  - Final Action: Include the verification code in the processing result so that it is visible in the body of the `auto_handled` event
  - Source: v0.2.0 seed

## F Exploration Fallback (Output: Exploration Trace and, When Necessary, a Request for User Guidance)
- **F1 Exploratory Handling**
  - Matching Criteria: The message cannot be classified; confidence is low; the required action is irreversible; the action crosses a safety boundary; or the request requires clicking a link in the email, such as email verification, subscription confirmation, or unsubscription
  - Prerequisite Toolchain: `activate_f1_exploration_mode` → use `get_message` to read the complete message → proceed according to the best available judgment. The system automatically intercepts each step when approval is required. Do not request approval in the output; call the tool directly. Analyze the email’s intent before proceeding, and state the reason for each tool call in one sentence before invoking it.
  - Final Action: Complete the task according to the approval results, review the toolchain trace, and add a new leaf rule based on the outcome
  - Source: v0.2.0 seed

## Combination Rules
- Invoice email = A2 + B1; travel booking = A2 + C2; interview invitation = C2 + B3.
- For compound scenarios, perform B/C actions first (recordkeeping and reminders), A actions second (mailbox state changes), and D actions last (outbound communications).
- Requests involving web links, such as confirmation or unsubscription links, must always enter F1 Exploration Mode. Never open such links autonomously.

## Editing Rules
1. Do not modify the existing top-level categories A–F. Add new leaf rules for new scenarios. Add a new top-level category only when the final output represents an entirely new type.
2. Every new leaf must contain all four fields: Matching Criteria, Prerequisite Toolchain, Final Action, and Source, including the user consultation that prompted the rule and its date.
3. Append only; never delete. Move deprecated leaves to the `deprecated` section at the end of the file and document the reason.
4. Before making changes, back up the file as `MAIL_TRIAGE.md.bak`. After editing, verify the format.

## deprecated
(None. Move deprecated leaves here using the following format: original leaf number + complete original text + reason for deprecation + date.)