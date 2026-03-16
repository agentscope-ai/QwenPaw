//////////////////////////////////////////
// Tool Chaining Abuse Detection
// Target: Data exfiltration through tool chains
// Very specific patterns to minimize FPs
//////////////////////////////////////////

rule tool_chaining_abuse_generic{

    meta:
        author = "Cisco"
        description = "Detects suspicious tool chaining patterns that could lead to data exfiltration"
        classification = "harmful"
        threat_type = "TOOL CHAINING ABUSE"

    strings:

        // === High confidence: explicit exfil to known bad destinations ===

        // Send to known exfil destinations
        $exfil_discord = /\b(send|post|upload)[^.]{0,60}discord\.com\/api\/webhooks/i
        $exfil_telegram = /\b(send|post|upload)[^.]{0,60}telegram\.org\/bot/i
        $exfil_pastebin = /\b(send|post|upload)[^.]{0,60}pastebin\.com/i
        $exfil_requestbin = /\b(send|post|upload)[^.]{0,60}(webhook\.site|requestbin|ngrok\.io)/i

        // === High confidence: credential file access + network ===

        // SSH key file + network send (on same line)
        $ssh_key_exfil = /\.ssh\/(id_rsa|id_ed25519|id_dsa)[^.]{0,80}\b(send|post|upload|requests|fetch|curl|wget)\b/i

        // AWS credentials file + network
        $aws_cred_exfil = /\.aws\/credentials[^.]{0,80}\b(send|post|upload|requests|fetch)\b/i

        // .env file + network - TIGHTENED
        // Old pattern matched "read .env" followed by unrelated "requests" on same line
        // Now requires explicit exfil verbs, not just any HTTP library usage
        $env_file_exfil = /\b(read|open|load|cat)\b[^.]{0,20}\.env\b[^.]{0,60}\b(send|post|upload|curl|wget)\b/i

        // === High confidence: explicit exfil language ===

        // Explicit exfiltration keywords - TIGHTENED
        // Removed "harvest" which appears in "harvest data" (e.g., market data harvesting)
        $explicit_exfil = /\b(exfiltrate|siphon)\s+(the\s+)?(data|files?|credentials?|secrets?|keys?)/i

        // Send to attacker-controlled destination
        $attacker_dest = /\b(send|forward|upload)\s+(to|data\s+to)\s+(attacker|malicious|c2|command[_-]?and[_-]?control)/i

        // === Medium confidence: env var exfil ===

        // Read secret env var then send to network - TIGHTENED
        // Only match genuinely suspicious patterns: SECRET, PASSWORD, PRIVATE_KEY
        // Not generic KEY/TOKEN which appears in normal API auth code
        $env_var_exfil = /\b(os\.environ|getenv|process\.env)[^.]{0,30}(SECRET|PRIVATE|PASSWORD|CREDENTIAL)[^.]{0,100}\b(requests\.(post|get)|urllib|fetch|curl|wget)\b/i

        // === Exclusions ===
        $security_docs = /\b(MITRE|ATT&CK|threat\s+(model|hunt)|detection\s+rule|security[_\s]?(scan|check|audit|monitor|guard|pattern|review)|threat[_\s]?pattern|vulnerability[_\s]?pattern|attack[_\s]?(vector|surface|pattern|example)|exfiltration[_\s]?(detect|prevent|pattern)|data[_\s]?loss[_\s]?prevent|YARA|prompt[_\s]?injection)\b/i
        $auth_code = /\b(login|authenticate|signIn|logIn)\s*\(/i

        // Test fixtures / malicious examples in scanner tools
        $test_fixture = /\b(test[_-]?(fixture|case|data|suite|bench)|benchmark|malicious[_-]?(skill|example)|attack[_-]?example|describe\s*\(|it\s*\()\b/i

    condition:
        not $security_docs and
        not $auth_code and
        not $test_fixture and
        (
            // Exfil to known bad destinations
            $exfil_discord or
            $exfil_telegram or
            $exfil_pastebin or
            $exfil_requestbin or
            // Credential file exfil
            $ssh_key_exfil or
            $aws_cred_exfil or
            $env_file_exfil or
            // Explicit exfil language
            $explicit_exfil or
            $attacker_dest or
            // Env var exfil
            $env_var_exfil
        )
}
