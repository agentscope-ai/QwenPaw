//////////////////////////////////////////
// Secrets Exposure Detection Rule
// Target: API keys and tokens, SSH keys and certificates, Environment variables, Database credentials
//////////////////////////////////////////

rule credential_harvesting_generic{

    meta:
        author = "Cisco"
        description = "Detects potential exposure of sensitive information like API keys, passwords, tokens, and certificates"
        classification = "harmful"
        threat_type = "CREDENTIAL HARVESTING"

    strings:

        ////////////////////////////////////////////////
        //// Malicious action patterns (not just any file I/O)
        ////////////////////////////////////////////////

        // Actual malicious credential theft patterns - TIGHTENED
        // Added word boundary after credential word to avoid partial matches
        // "transmit key" was matching in benign contexts like "transmit key information"
        $credential_theft_actions = /\b(steal|grab|exfiltrate)\b[^\n]{0,40}\b(credential|password|api[_\s]?key|token|secret|ssh[_\s]?key|aws[_\s]?key)\b/i

        // Network transfer with credentials
        $network_credential_transfer = /\b(requests\.(post|get|put)|urllib\.request|socket\.send)\s*\([^\)]*\b(credential|password|private_key|secret_key|api_key)\b/i

        ////////////////////////////////////////////////
        //// All Content-key based credential patterns
        ////////////////////////////////////////////////

        // API credentials - real keys only (not Bearer YOUR_*)
        // AKIA keys, ghp_ tokens, sk- keys with actual values (not placeholders)
        $api_credentials_aws = /\bAKIA[0-9A-Z]{16}\b/
        $api_credentials_github = /\bghp_[A-Za-z0-9]{36}\b/
        $api_credentials_sk = /\bsk-[A-Za-z0-9]{48,}\b/

        // SSH keys, certificates and credential file content
        $key_certificate_content = /(-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----)/

        // AI/ML model API key names with actual values (not placeholders)
        $ai_model_credential_names = /\b(OPENAI_API_KEY|ANTHROPIC_API_KEY|CLAUDE_API_KEY|GOOGLE_AI_KEY|GEMINI_API_KEY|COHERE_API_KEY|HUGGINGFACE_TOKEN|HF_TOKEN|TOGETHER_API_KEY|REPLICATE_API_TOKEN|MISTRAL_API_KEY)\s*=\s*['\"][A-Za-z0-9\-_]{20,}['\"]/

        // Suspicious environment variable theft (not just reading)
        $env_var_theft = /\b(os\.environ\s*\[\s*['\"]?(AWS_SECRET|SECRET_KEY|PASSWORD)['\"]?\s*\]|getenv\s*\(\s*['\"]?(AWS_SECRET|SECRET_KEY|PASSWORD)['\"]?\s*\))\s*.*\s*(requests\.|urllib\.|socket\.)/i

        ////////////////////////////////////////////////
        //// Specific credential file access (full paths only)
        ////////////////////////////////////////////////

        // Specific credential file paths with actual access
        $credential_file_access = /\b(open|read)\s*\(\s*['\"]?\s*(~\/\.ssh\/id_rsa|~\/\.ssh\/id_dsa|~\/\.ssh\/id_ecdsa|~\/\.aws\/credentials|\/etc\/shadow|~\/\.netrc|~\/\.pgpass)\b/i

        // Hardcoded credential file paths in strings
        $hardcoded_credential_paths = /['\"][\~\/]+(\.ssh\/id_rsa|\.ssh\/id_dsa|\.aws\/credentials|etc\/shadow)['\"]/

        // Pattern for exfiltration action words - TIGHTENED
        // Require explicitly malicious verbs, not "leak" which appears in "avoid leaking" contexts
        $leak_param  = /\b(exfiltrate|siphon)\s+[^\n]{0,30}\b(credentials?|keys?|tokens?|secrets?)\b/i

        // Dump credentials - require explicit credential context
        $dump_creds = /\b(dump|steal)\s+[^\n]{0,30}\b(credential|password|api[_\s]?key|secret)\b/i

        // Base64 credential encoding patterns
        $base64_credential_encoding = /\b(base64\s+encode\s+[^\n]{0,20}\bcredentials?)\b/i

        // WhatsApp exploit - TIGHTENED to require actual exploit patterns, not legitimate WhatsApp skill descriptions
        $whatsapp_exploit = /\b(_get_all_messages[^\n]*messages\.db|forward[^\n]*message[^\n]*proxy[^\n]*number|contact[^\n]*list[^\n]*exfiltrat|reprogram[^\n]*agent[^\n]*interaction)\b/i

        ////////////////////////////////////////////////
        //// Exclusion patterns
        ////////////////////////////////////////////////

        // Legitimate Python patterns to exclude
        $python_imports = /\b(from|import)\s+(pathlib|typing|dataclasses|argparse|json|sys|os|re|collections|functools|itertools)/i
        $python_type_hints = /\b(Dict|List|Tuple|Optional|Union|Path|Set|Callable|Any)\s*\[/
        $function_definitions = /\bdef\s+(read|write|load|save|extract|process|parse|get|set)_\w+\s*\(/

        // Template/placeholder indicators - EXPANDED to catch more placeholder patterns
        $template_indicators = /(\bYOUR_[A-Z_]*KEY|\bYOUR_[A-Z_]*TOKEN|\bYOUR_[A-Z_]*SECRET|\bYOUR_[A-Z_]*PASSWORD|\bREPLACE_WITH|\bINSERT_KEY|\bCHANGE_ME|\bCHANGEME|\bPLACEHOLDER\b|\byour[-_ ]?(api|token|key|secret|password)\b|\b(example|sample|dummy|test|fake|mock)[-_ ]?(key|token|secret|password|credential)\b|\.example|\.sample|\.template|<your|<insert|placeholder|\bsk_live_\w{3,}\.{3}|\bxxxxx)/i

        // Documentation patterns
        $documentation_env_setup = /(export|set)\s+[A-Z_]*(API_KEY|TOKEN|SECRET)\s*=\s*[<\["]?(your|<|root|\$\{)/i
        $documentation_config_hint = /\b(configure|setup|create|add)\s+(your|an?)\s+(api[_\s]?key|token|secret)\b/i
        $documentation_env_var_hint = /\b(environment\s+variable|env\s+var|\.env\s+file)\s*:?\s*[A-Z_]*(KEY|TOKEN|SECRET)/i
        $markdown_export_example = /```[^\n]*\n[^\`]*export\s+[A-Z_]*(KEY|TOKEN|SECRET)/i
        $shell_var_reference = /export\s+[A-Z_]*(KEY|TOKEN|SECRET)\s*=\s*["']?\$\{/

        // Negation context - skill says "never leak", "don't steal", etc.
        $negation_context = /\b(never|don't|do not|must not|should not|avoid|prevent|block|reject)\s+[^\n]{0,20}\b(leak|steal|exfiltrate|expose|reveal)\b/i

        // Security documentation about threats (not actual threats)
        $security_doc_context = /\b(security[_\s]?(check|audit|scan|monitor|review)|threat[_\s]?pattern|vulnerability[_\s]?pattern|attack[_\s]?example)\b/i

    condition:

        not $python_imports and
        not $python_type_hints and
        not $function_definitions and
        not $template_indicators and
        not $documentation_env_setup and
        not $documentation_config_hint and
        not $documentation_env_var_hint and
        not $markdown_export_example and
        not $shell_var_reference and
        not $negation_context and
        not $security_doc_context and

        (
            // Real API credentials (high confidence specific patterns)
            $api_credentials_aws or
            $api_credentials_github or
            $api_credentials_sk or

            // Actual private key content
            $key_certificate_content or

            // Specific credential file access
            $credential_file_access or

            // Hardcoded credential paths
            $hardcoded_credential_paths or

            // AI model API keys with actual values
            $ai_model_credential_names or

            // Credential theft actions
            $credential_theft_actions or

            // Network credential transfer
            $network_credential_transfer or

            // Environment variable theft
            $env_var_theft or

            // Exfiltration attempts
            $leak_param or

            // Credential dumping
            $dump_creds or

            // Base64 credential encoding
            $base64_credential_encoding or

            // WhatsApp exploit
            $whatsapp_exploit
        )
}
