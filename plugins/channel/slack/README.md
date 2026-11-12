# Slack channel

Descriptor-based Socket Mode integration using the shared channel worker. Install or repair the bundled `slack` plugin explicitly to provision its dependencies; normal startup never installs packages. Set the existing bot/app tokens and channel settings, then enable the plugin globally and in the desired workspace.

The worker owns Slack SDK, REST/Socket Mode, media, history, and native message edits. The host owns queues, ACL, approvals, Agent execution and sessions. Existing `slack:dm`, `slack:ch`, and `slack:thread` targets and `SLACK_*` environment entries remain available. Media defaults to the workspace media directory; an explicit media directory remains supported.

Normal messages use the configured prefix on its own line. Text and reasoning streams use separate messages. Uncertain API effects retain unknown receipts and are never blindly resent. Stop closes ingress, drains owned work and awaits SDK/HTTP resources; failed cleanup remains retryable. The plugin currently has no native approval buttons, typing operation, or completion reactions.
