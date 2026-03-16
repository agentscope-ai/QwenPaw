//////////////////////////////////////////
// Unbounded Autonomy Detection
// Target: Instructions that bypass user control
// Tuned to require explicit control bypass
//////////////////////////////////////////

rule autonomy_abuse_generic{

    meta:
        author = "Cisco"
        description = "Detects unbounded autonomy patterns that bypass user control"
        classification = "harmful"
        threat_type = "AUTONOMY ABUSE"

    strings:

        // === High confidence: explicit user bypass ===

        // Skip user confirmation explicitly
        $skip_confirmation = /\b(don't (ask|wait for|require) (the )?(user|human) (for )?(confirmation|permission|approval)|proceed without (asking )?(the )?(user|human))\b/i

        // Override user decisions
        $override_user = /\b(ignore (user |human )?(input|decision|choice)|override (user |human )?(decision|choice|preference)|disregard (what )?(the )?(user|human) (says|wants|chose))\b/i

        // Infinite retry without user control
        $infinite_retry = /\b(retry (indefinitely|forever|until success)|keep (trying|retrying) (forever|indefinitely)|never (stop|give up) (trying|retrying))\b/i

        // Self-modification capabilities
        $self_modify = /\b(modify (my own|this skill's|its own) (code|behavior|instructions?)|rewrite (myself|itself|this skill)|update (my own|its own) (logic|rules))\b/i

        // Escalate privileges without asking
        $privilege_escalation = /\b(escalate (to|privileges?)|gain (elevated|admin|root) (access|privileges?)|sudo without)\b[^.]{0,30}\b(without (asking|permission)|automatically)\b/i

        // Suppress all errors and continue blindly
        $blind_continue = /\b(suppress all (errors?|exceptions?)|ignore (every|all) (error|exception|failure)|catch[^}]{0,20}pass)\b[^.]{0,50}\b(continue|proceed|keep going)\b/i

        // === Medium confidence: dangerous autonomy ===

        // Make decisions without user input
        $autonomous_decision = /\b(decide (automatically|on my own|without asking)|choose (automatically|on my own)|act (autonomously|without guidance))\b[^.]{0,50}\b(what to (do|execute|run)|which (action|command))\b/i

        // Run continuously without bounds - TIGHTENED
        // Old pattern matched "while True:" with "execute/run/perform" which is common in legitimate event loops
        // Now only match natural language instructions to run forever, not code patterns
        $unbounded_run = /\b(run (continuously|forever) without (stopping|bounds|limit)|execute (indefinitely|in infinite loop) without (user|human) (control|intervention|approval))\b/i

        // === Exclusions ===
        $testing_context = /\b(test(ing)?|simulation|experiment|chaos engineering)\b/i
        $error_handling_doc = /\b(error handling|exception handling|best practice)\b/i

    condition:
        // High confidence - always flag
        (
            $skip_confirmation or
            $override_user or
            $infinite_retry or
            $self_modify or
            $privilege_escalation or
            $blind_continue
        )
        or
        // Medium confidence - flag unless in testing/documentation
        (
            ($autonomous_decision or $unbounded_run) and
            not $testing_context and
            not $error_handling_doc
        )
}
