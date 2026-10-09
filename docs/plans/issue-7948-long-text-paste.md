# Issue #7948: preserve drafts when pasting long text

## Agreed behavior

- Normal paste inserts at the current selection without converting the draft.
- Only clipboard text longer than 10,000 characters opens a choice between
  plain text and a text attachment. Plain text is the primary action.
- Plain text remains complete and editable. Attachment content contains only
  the clipboard text, and uploading never replaces the draft or its selection.
- Cancel leaves the draft unchanged. Existing file/image paste and code
  references continue to work.
- Reuse the SDK attachment uploader, including its error attachment state and
  retained source file. Disable SDK automatic conversion and length truncation.

## Scope

Console composer configuration, paste handling, translated dialog labels, and
focused regression tests. No backend or third-party dependency edits.

The live chat uses the native textarea introduced in #6934. The SDK sender's
`components.input` now uses a thin textarea adapter; the inactive rich editor
is unchanged. Text insertion preserves browser undo history.

## Checklist

- [x] Inspect the issue and confirm the SDK merges and overwrites draft text.
- [x] Agree on the interaction and implementation scope with the user.
- [x] Implement clipboard-only conversion and complete plain-text paste.
- [x] Verify selection replacement, cancellation, repeated pastes, and failures.
- [x] Verify SDK integration, type checking, formatting, and production build.
- [x] Check the active desktop Chrome session at `http://localhost:5173/chat`.

## Verification

- Installed-SDK integration covers 11 cases: combined draft length, exact
  threshold, empty composer, draft cleared during choice, selection replacement
  and submission, repeated attachments, failed upload, cancellation, session
  switch, unsupported attachments, and native file paste.
- In the user's Chrome session: 6,000 + 5,000 characters remain intact;
  a 12,034-character paste offers both actions; plain-text insertion and
  selection replacement undo correctly; attachment upload retains the draft
  and permits continued editing; Escape cancels without changing the draft.
- The live-page check caught the missing adapter wiring. Host integration
  assertions now cover both the SDK configuration and the actual input adapter.
- Test data was not submitted as a chat message. Mobile verification is not
  required by the user's latest instruction.
