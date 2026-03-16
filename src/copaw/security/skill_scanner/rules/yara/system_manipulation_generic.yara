//////////////////////////////////////////
// System Manipulation and Privilege Escalation Detection
// Target: File destruction and manipulation operations
// (Process control and termination)
//////////////////////////////////////////

rule system_manipulation_generic{

    meta:
        author = "Cisco"
        description = "Detects system manipulation, privilege escalation, and destructive file operations"
        classification = "harmful"
        threat_type = "SYSTEM MANIPULATION"

    strings:
        // Suspicious environment variable manipulation - TIGHTENED
        // Removed "export PATH=" which is normal in shell scripts
        // Only match clearly malicious path manipulation or unsetting critical vars
        $env_var_manipulation = /\b(unset\s+(PATH|HOME|USER)|export\s+PATH=\.\:)\b/i

        // File destruction - TIGHTENED
        // Bare "rm -rf" without a dangerous path is too common (build cleanup, etc.)
        // Only match truly destructive patterns: dd zero, wipefs, shred
        // rm -rf with dangerous paths is handled by $recursive_operations
        $file_destruction = /\b(dd\s+if=\/dev\/zero\s+of=\/|wipefs\s+(-a\s+)?\/|shred\s+-[a-z]*\s+\/)\b/i

        // Dangerous file permission changes
        $permission_manipulation = /\b(chmod\s+(777|4755|6755|[ug]\+s)\s+\/)|(chown\s+root\s+\/)\b/i

        // Critical system file access - TIGHTENED
        // Only match write/modify access to critical files, not just mentioning paths
        // Removed /etc/passwd and ~/.aws/credentials and ~/.ssh/id_rsa (too common in docs)
        $critical_system_write = /\b(echo|cat|tee|write|>>?)\s+[^\n]*(\/etc\/(shadow|sudoers))\b/i

        // Privilege escalation patterns - TIGHTENED
        // Removed bare "su -" which is common. Only match sudo -s/-i
        $privilege_escalation = /\b(sudo\s+-[si]|runuser|doas)\b/i

        // Dangerous process operations - TIGHTENED
        // "kill -9 2" matched on PIDs like 2xxx. Require explicit dangerous context
        $process_manipulation = /\b(killall\s+-9\s+\w+|pkill\s+-9\s+\w+)\b/i

        // Dangerous recursive operations with system-critical paths.
        // Match root-like targets only (/, /etc, /usr, /root, /home, $HOME, ~/)
        // and avoid matching routine subdirectory cleanup like ~/Library/...
        $recursive_operations = /\brm\s+-rf\s+(\/\s|\/root(?:\s|\/\*|$)|\/home(?:\s|\/\*|$)|\$HOME(?:\s|\/\*|$)|~\/(?:\s|\*|$)|\/etc(?:\s|\/\*|$)|\/usr(?:\s|\/\*|$))/i

        // Safe cleanup patterns to exclude - EXPANDED
        $safe_cleanup = /(rm\s+-rf\s+(\/var\/lib\/apt\/lists|\/tmp\/|node_modules|__pycache__|\.cache|\.npm|\/var\/cache|dist\/|build\/|target\/|\.git\/|coverage\/|\.tox\/|\.mypy_cache|\.pytest_cache|\.next\/|\.nuxt\/|out\/|\.turbo\/)|find\s+[^\n]*-mtime\s+\+[0-9]+[^\n]*-delete|find\s+[^\n]*backup[^\n]*-delete|rm\s+-rf\s+\$\{?[A-Za-z_]+\}?\/)/i

        // Testing and build commands
        $testing_commands = /\b(pytest|tox|make\s+test|npm\s+test|cargo\s+test|go\s+test|mvn\s+test|gradle\s+test|jest|mocha)\b/i

        // Safe directory creation
        $safe_mkdir = /\bmkdir\s+-p\b/

        // System path manipulation (inject current dir or tmp into PATH)
        $path_manipulation = /\b(PATH=\/tmp|PATH=\.\:|export\s+PATH=\.\:)\b/i

        // Documentation context - mentioning these in security docs is not an attack
        $security_doc_context = /\b(security[_\s]?(check|audit|scan|best.practice|guide)|threat[_\s]?pattern|vulnerability|remediat)\b/i

    condition:
        not $safe_cleanup and
        not $testing_commands and
        not $safe_mkdir and
        not $security_doc_context and
        (
            // Environment variable manipulation
            $env_var_manipulation or

            // File destruction
            $file_destruction or

            // Permission manipulation
            $permission_manipulation or

            // Critical system file writes
            $critical_system_write or

            // Privilege escalation
            $privilege_escalation or

            // Process manipulation
            $process_manipulation or

            // Recursive operations on system paths
            $recursive_operations or

            // PATH manipulation
            $path_manipulation
        )
}
