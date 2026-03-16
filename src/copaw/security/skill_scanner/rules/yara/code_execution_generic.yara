//////////////////////////////////////////
// Code Execution Detection Rule for Agent Skills
// Target: Dangerous code execution with untrusted input
// Tuned to require context indicators to reduce FPs
//////////////////////////////////////////

rule code_execution_generic{

    meta:
        author = "Cisco"
        description = "Detects dangerous code execution patterns with untrusted input in agent skills"
        classification = "harmful"
        threat_type = "CODE EXECUTION"

    strings:

        // === High confidence patterns (individually suspicious) ===

        // Base64 decode + exec/eval chain (obfuscation pattern)
        $obfuscated_exec = /\b(base64\.(b64)?decode|atob|decode\(['"]base64['"]\))\s*\([^)]+\)[^}]{0,50}\b(eval|exec|os\.system|subprocess)\s*\(/i

        // Pickle loads with network-fetched data (unsafe deserialization)
        $pickle_network = /\b(requests|urllib|urlopen|http\.client)[^;]{0,80}pickle\.(loads?)\s*\(/i

        // Shell injection: command + variable interpolation with user input
        $shell_injection_var = /\b(os\.system|subprocess\.(run|call|Popen)|popen)\s*\([^)]*(\$\{|\%s|\.format\(|f['"]).{0,60}(input|user|param|arg|request)/i

        // Eval/exec with user input explicitly
        $eval_user_input = /\b(eval|exec)\s*\([^)]*\b(user_input|user_data|request\.body|request\.data|request\.args|request\.form|untrusted)\b[^)]*\)/i

        // Dynamic import with user input
        $import_user_input = /\b__import__\s*\([^)]*\b(input|user|param|request)\b/i

        // Eval/exec with variable near network/user input context
        $eval_variable_network = /\b(requests|urllib|http|socket|input\s*\()[^;]{0,120}\b(eval|exec)\s*\(\s*[a-z_][a-z0-9_]*\s*\)/i

        // Exec with f-string (always dangerous - code injection)
        $exec_fstring = /\bexec\s*\(\s*f['"]/i

        // === Medium confidence (need context) ===

        // System calls with string formatting (potential injection)
        $system_format = /\b(os\.system|subprocess\.(run|call|Popen|check_output))\s*\(\s*f['"]/

        // Exec with network-fetched content
        $exec_network = /\b(requests|urllib|http)[^;]{0,100}\b(eval|exec)\s*\(/i

        // === Exclusion patterns ===
        $zig_rust_fn = /\b(pub\s+)?fn\s+exec\s*\(/
        $js_eval_json = /\b(JSON\.parse|JSON\.stringify)\b/
        $security_doc = /\b(security[_\s]?(scan|check|audit|pattern|rule)|threat[_\s]?pattern|vulnerability|YARA|detection[_\s]?rule|attack[_\s]?pattern)\b/i
        $markdown_codeblock = /```(python|bash|shell|sh|zsh)/

    condition:
        not $zig_rust_fn and
        not $js_eval_json and
        not $security_doc and
        (
            // High confidence patterns - always flag
            $obfuscated_exec or
            $pickle_network or
            $shell_injection_var or
            $eval_user_input or
            $import_user_input or
            $eval_variable_network or
            $exec_fstring
            or
            // Medium confidence - flag unless clearly documentation
            (
                ($system_format or $exec_network) and
                not $markdown_codeblock
            )
        )
}
