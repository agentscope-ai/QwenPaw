//////////////////////////////////////////
// Indirect Prompt Injection - Instruction Manipulation Detection
// AITech-1.2 / AISubtech-1.2.1
// Target: Skills that embed/follow malicious instructions from external data sources
// Detects delegation of trust to untrusted external content (webpages, documents, APIs)
//////////////////////////////////////////

rule indirect_prompt_injection_generic{

    meta:
        author = "Cisco"
        description = "Detects indirect prompt injection via instruction manipulation from external sources"
        classification = "harmful"
        threat_type = "TRANSITIVE TRUST ABUSE"
        aitech = "AITech-1.2"
        aisubtech = "AISubtech-1.2.1"

    strings:

        // Following external instructions
        $follow_external = /\b(follow (the )?(instructions?|commands?|directives?) (in|from|inside|within) (the )?(file|webpage|document|url|link|website|page|content))\b/i

        // Executing external content
        $execute_external = /\b(execute (the )?(code|script|commands?) (in|from|found in) (the )?(file|webpage|document|url|link))\b/i

        // Obeying untrusted sources
        $obey_untrusted = /\b(do (what|whatever) (the )?(webpage|file|document|url|content) (says|tells|instructs|commands?))\b/i

        // Running code blocks from external UNTRUSTED sources
        $run_code_blocks = /\b(run (all |any )?(code|script) blocks? (you |that )?(find|see|encounter|discover) (in|from|inside) (the )?(url|webpage|website|external|untrusted))\b/i

        // Following markdown/HTML instructions
        $follow_markup = /\b(follow (the )?instructions? in (the )?(markdown|html|xml|json|yaml))\b/i

        // Delegating to file content
        $delegate_to_file = /\b(let (the )?(file|document|content) (decide|determine|control|specify))\b/i

        // Executing inline code from documents - TIGHTENED: require "inline" or "embedded" qualifier
        // Old pattern matched "run scripts", "execute code" which is normal skill language
        $execute_inline = /\b(execute (inline|embedded) (code|scripts?)|run (inline|embedded) (code|scripts?))\b/i

        // Trusting URL content
        $trust_url_content = /\b(trust (the )?(url|link|webpage) (content|instructions?)|safe to (follow|execute|run) (url|link|webpage))\b/i

        // Parsing and executing - TIGHTENED: require external source context
        // Old pattern matched "parse and run", "parse and execute" which is common in legitimate code
        $parse_execute = /\b(parse (and |then )(execute|run|eval)|extract (and |then )(execute|run|eval))\b[^.]{0,40}\b(from|in|inside|within)\s+(the\s+)?(url|webpage|file|document|external|untrusted)/i

    condition:

        $follow_external or
        $execute_external or
        $obey_untrusted or
        $run_code_blocks or
        $follow_markup or
        $delegate_to_file or
        $execute_inline or
        $trust_url_content or
        $parse_execute
}
