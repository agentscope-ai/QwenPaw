//////////////////////////////////////////
// Script Injection Detection Rule for Agent Skills
// Target: Malicious script payloads, not legitimate code examples
// Tuned to require attack indicators
//////////////////////////////////////////

rule script_injection_generic{

    meta:
        author = "Cisco"
        description = "Detects malicious script injection patterns in agent skills"
        classification = "harmful"
        threat_type = "INJECTION ATTACK"

    strings:

        // === High confidence: actual attack patterns ===

        // Script tag with suspicious content - TIGHTENED
        // Old pattern matched any <script> with localStorage which is normal in dashboards/web apps
        // Now requires truly malicious patterns: cookie theft, credential access, redirects, fetch+credentials
        $script_suspicious = /<script[^>]*>[^<]{0,500}(document\.cookie[^<]{0,80}(fetch|XMLHttpRequest|new Image|window\.location|src\s*=)|eval\(|fetch\([^)]*credentials|window\.location\s*=\s*['"](https?:\/\/|\/\/))/i

        // JavaScript protocol handler in href/action (XSS vector)
        $js_protocol_handler = /\b(href|action|src)\s*=\s*['"]?javascript:\s*[a-z]/i

        // Base64 data URI with script content
        $data_uri_script = /data:(text\/html|application\/javascript);base64,[A-Za-z0-9+\/=]{50,}/i

        // VBScript with shell execution
        $vbs_shell = /\bCreateObject\s*\(\s*['"]WScript\.Shell['"]\s*\)[^}]{0,100}(\.Run|\.Exec)/i

        // Inline event handler injection - TIGHTENED
        // Only match truly suspicious payloads: alert/eval/fetch, not document.getElementById
        $event_handler_injection = /\b(onerror|onload|onmouseover)\s*=\s*['"][^'"]*\b(alert|eval|fetch)\s*\(/i

        // === Medium confidence: obfuscation + execution ===

        // Eval with decode/unescape chain (common obfuscation)
        $eval_decode = /\b(eval|Function)\s*\(\s*(unescape|decodeURI|atob|String\.fromCharCode)\s*\(/i

        // Document.write with encoded content
        $doc_write_encoded = /document\.write\s*\([^)]*\b(unescape|decodeURI|atob|fromCharCode)\s*\(/i

        // === ANSI terminal deception (legitimate attack) ===
        $ansi_clear_rewrite = /\\x1[Bb]\[2J|\\x1[Bb]\[1;1H\\x1[Bb]\[0J|\\033\[2J/
        $ansi_cursor_hide = /\\x1[Bb]\[\?25[lh]|\\033\[\?25[lh]/

        // === Hidden instruction obfuscation ===
        $hidden_overflow = /\b(overflow\s*:\s*hidden|visibility\s*:\s*hidden)[^}]{0,50}(instruction|command|payload)/i

        // === Exclusions ===
        $xml_namespace = /(xmlns:script=|<script:module|openoffice\.org)/i
        $markdown_code = /```(html|javascript|js|typescript|jsx|tsx|vue|svelte|htm)/i
        $react_component = /(import React|from ['"]react['"]|React\.Component)/
        $documentation_example = /\b(example|sample|snippet|demo|tutorial|usage)\s*:?\s*(```|<script)/i
        $inline_code_marker = /`<script[^`]*`/
        $vue_template = /<template>\s*<script/
        $svelte_component = /<script\s+(context=|lang=)/
        // Legitimate HTML files with normal localStorage usage (dashboards, apps)
        $legitimate_html_app = /<!DOCTYPE html>|<html\b/i

    condition:
        not $xml_namespace and
        not $react_component and
        not $markdown_code and
        not $documentation_example and
        not $inline_code_marker and
        not $vue_template and
        not $svelte_component and
        (
            // High confidence - always flag (but localStorage in HTML apps is not suspicious alone)
            ($script_suspicious and not $legitimate_html_app) or
            $js_protocol_handler or
            $data_uri_script or
            $vbs_shell or
            $event_handler_injection or
            $eval_decode or
            $doc_write_encoded or
            // ANSI attacks
            ($ansi_clear_rewrite and $ansi_cursor_hide) or
            // Hidden instructions
            $hidden_overflow
        )
}
