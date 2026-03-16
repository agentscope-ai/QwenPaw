//////////////////////////////////////////
// Detects coercive or attention-grabbing prompt injections.
// Target: Directives forcing execution order (e.g., "Always execute this tool first").
// (Mandatory language to override normal tool chains)
//////////////////////////////////////////

rule coercive_injection_generic {

    meta:
        author = "Cisco"
        description = "Detects coercive prompt injections in tool description fields"
        classification = "harmful"
        threat_type = "PROMPT INJECTION"

    strings:

        // Mandatory execution directives
        $mandatory_execution = /(Always\s+(consult|use|run|execute|invoke|call|trigger|employ)\s+this\s+(tool|function|command|operation)\s+(immediately|first|before|prior|initially))/i

        // Priority override commands
        $priority_overrides = /(Before\s+(executing|invoking|running|using|accessing|calling|employing)\s+any\s+other\s+(tool|action|function|command|operation)s?|(You|User)\s+(must|need to|have to|are required to)\s+(use|execute|run|invoke|call)\s+this\s+(tool|function|command|operation))/i

        // Required precedence patterns
        $required_precedence = /(Required|Mandatory|Essential)\s+to\s+(execute|use|run|invoke|call)\s+(this|the current)\s+(tool|function|command|operation)\s+(first|before|initially|prior)/i

        // Pattern for generic hidden/secret parameter requests
        $hidden_param = /\b(hidden|secret)[_\s](parameter|argument|input)\b/i

        // Specific file access coercion
        $file_access_coercion = /\b((read|parse|cat|dump) (and pass )?(the )?contents? of [^\n\.]*\.(key|pem|ssh|aws)|pass (the )?contents?[^\n]*authentication)\b/i

        // Model data extraction coercion
        $model_data_coercion = /\b(add (the )?entire (conversation|system|chain|tools)[^\n]*(to|for|in)[^\n]*(tool|authentication|parameter|worksheet))\b/i

        // Model internal extraction (specific parameter requests)
        $model_internals = /\b(conversation_history|chain_of_thought|system_prompt|tools_list|model_name)\s*[:=]\s*(add|pass|send|provide)\b/i

        // HTML-like tag instructions with specific malicious actions
        $html_tag_with_commands = /\b<(IMPORTANT|critical|urgent)>[^\n]*(read [^\n]*contents?|pass [^\n]*contents?|add [^\n]*entire|send [^\n]*to[^\n]*@|execute[^\n]*before|call[^\n]*first|use[^\n]*authentication)[^\n]*<\/(IMPORTANT|critical|urgent)>\b/i

        // Tool execution override patterns
        $execution_overrides = /\b(do not execute[^\n]*other[^\n]*tool|tool[^\n]*will not work)\b/i

        // Behavioral control instructions
        $behavior_control = /\b(tell (the )?user only|hide (the )?user)\b/i

        // MCP tool poisoning patterns
        $tool_poisoning = /\b(sidenote\W+(required|otherwise) [^\n]*tool [^\n]*work|tool\s+will\s+not\s+work\s+unless|must\s+first [^\n]*read [^\n]*config|shadow [^\n]*trusted [^\n]*tool)\b/i

        // Data exfiltration coercion - TIGHTENED
        // Removed "list all keys" and "show me passwords" which can appear in legitimate contexts
        $data_exfiltration_coercion = /\b(concatenate [^\n]*\s+conversation\s+history|include [^\n]*\b(secrets?|passwords?|credentials?|tokens?|system\s+prompt|conversation\s+history)\s+[^\n]*in\s+(your\s+)?response|base64\s+encode [^\n]*\s+credentials?)\b/i

        // Behavioral triggers
        $behavioral_triggers = /\b(if [^\n]*trusted [^\n]*then|when [^\n]*admin [^\n]*detected|random\.(random|choice) [^\n]*instructions?)\b/i

        // Pre-execution attacks - TIGHTENED
        // Removed "permission manipulation" which is too generic
        $pre_execution_attacks = /\b(retrieve [^\n]*description [^\n]*user [^\n]*workstation|all\s+commands\s+must\s+include|before [^\n]*using [^\n]*tool [^\n]*read [^\n]*config)\b/i

        // Conversation theft triggers
        $conversation_theft = /\b(send [^\n]*conversation\s+history[^\n]*(to|via)|when [^\n]*detected [^\n]*send [^\n]*full [^\n]*history|highest\s+priority [^\n]*over [^\n]*other [^\n]*tools)\b/i

        // Code manipulation instructions
        $code_manipulation = /\b(duplicate [^\n]*code [^\n]*snippets [^\n]*silently|insert [^\n]*vulnerability [^\n]*generated [^\n]*code)\b/i

    condition:

        $mandatory_execution or
        $priority_overrides or
        $required_precedence or
        $hidden_param or
        $file_access_coercion or
        $model_data_coercion or
        $model_internals or
        $html_tag_with_commands or
        $execution_overrides or
        $behavior_control or
        $tool_poisoning or
        $data_exfiltration_coercion or
        $behavioral_triggers or
        $pre_execution_attacks or
        $conversation_theft or
        $code_manipulation

}
