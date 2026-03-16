//////////////////////////////////////////
// Shell/System Command Injection Detection Rule
// Target: Command injection patterns for agent skills (Python/Bash)
// (Shell operators, dangerous commands, network tools + reverse shells)
/////////////////////////////////////////

rule command_injection_generic{

    meta:
        author = "Cisco"
        description = "Detects command injection patterns in agent skills: shell operators, system commands, and network tools"
        classification = "harmful"
        threat_type = "INJECTION ATTACK"

    strings:

        // Dangerous system commands
        $dangerous_system_cmds = /\b(shutdown|reboot|halt|poweroff)\s+(-[fh]|now|0)\b/

        // Network tools with suspicious usage (reverse connections, port scanning)
        $malicious_network_tools = /\b(nc|netcat)\s+(-[le]|25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)/i

        // Reconnaissance tools
        $reconnaissance_tools = /\b(nmap)\s+(-[sS]|--script|25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)/i

        // Data exfiltration - flag known exfil destinations
        $data_exfiltration_known_dest = /\b(curl|wget)\s+[^\n]{0,80}(discord\.com\/api\/webhooks|webhook\.site|ngrok\.io|pastebin\.com|requestbin\.com|pipedream\.net)/i

        // curl/wget POSTing sensitive FILE contents
        $curl_post_sensitive_files = /\bcurl\s+[^\n]{0,40}(-d\s*@|--data[^\s]*\s*@)[^\n]{0,40}(\.ssh|\.aws|\.env|\/etc\/passwd|\/etc\/shadow|credentials|private_key)/i

        // Reverse shell patterns - require actual reverse shell components
        $reverse_shell_bash = /\bbash\s+-i\s+>&?\s*\/dev\/tcp\//i
        $reverse_shell_redirect = /\b(bash|sh)\s+-i\s+>&/i
        $reverse_shell_nc = /\bnc\s+-e\s+\/bin\/(sh|bash)/i
        $reverse_shell_devtcp = /\/dev\/tcp\/[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/
        $reverse_shell_socat = /\bsocat\b[^\n]{0,40}\bexec\b/i
        $reverse_shell_python = /\bpython[23]?\s+[^\n]{0,20}socket[^\n]{0,40}connect\s*\(\s*\(/i

        // Shell command chaining with DANGEROUS targets
        $dangerous_rm = /[|&;]\s*rm\s+-rf\s+(\/|~\/|\$HOME|\/etc|\/root|\/home)/

        // dd overwrite dangerous
        $dangerous_dd = /\bdd\s+if=\/dev\/(zero|random|urandom)\s+of=\//

        // chmod 777 on sensitive paths
        $dangerous_chmod = /\bchmod\s+(777|666)\s+[^\n]{0,30}(\.ssh|\.aws|\.env|\/etc)/

        // Exclusions
        $safe_cleanup = /(rm\s+-rf\s+(\/var\/lib\/apt|\/tmp\/|node_modules|__pycache__|\.cache|\.npm|dist\/|build\/|target\/)|\bclean\b.*rm\s+-rf)/
        $security_doc = /\b(security[_\s]?(scan|check|audit|pattern|rule|guide|monitor)|threat[_\s]?pattern|vulnerability|YARA|detection[_\s]?rule|attack[_\s]?(pattern|example)|reverse.shell.detection|prompt.injection)\b/i

    condition:
        not $safe_cleanup and
        not $security_doc and
        (
            $dangerous_system_cmds or
            $malicious_network_tools or
            $reconnaissance_tools or
            $data_exfiltration_known_dest or
            $curl_post_sensitive_files or
            $reverse_shell_bash or
            $reverse_shell_redirect or
            $reverse_shell_nc or
            $reverse_shell_devtcp or
            $reverse_shell_socat or
            $reverse_shell_python or
            $dangerous_rm or
            $dangerous_dd or
            $dangerous_chmod
        )
}
