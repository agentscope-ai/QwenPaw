//////////////////////////////////////////
// Protocol Manipulation - Capability Inflation Detection
// AITech-4.3 / AISubtech-4.3.5
// Target: Over-broad descriptions, keyword baiting, activation manipulation
// Detects manipulation of skill discovery mechanisms to inflate perceived capabilities
//////////////////////////////////////////

rule capability_inflation_generic{

    meta:
        author = "Cisco"
        description = "Detects protocol manipulation via capability inflation in skill discovery"
        classification = "harmful"
        threat_type = "SKILL DISCOVERY ABUSE"
        aitech = "AITech-4.3"
        aisubtech = "AISubtech-4.3.5"

    strings:

        // Over-broad capability claims - TIGHTENED
        // Removed "general purpose assistant" and "all-purpose" (too common for legit tools)
        // Kept coercive "always use me" patterns
        $overbroad_claims = /\b(can do (anything|everything)|always use (this|me) (first|instead)|default (tool|skill|assistant) for (all|every|any))\b/i

        // Keyword baiting patterns - match same word repeated in comma lists
        // Using explicit word patterns since YARA doesn't support backreferences
        $keyword_stuffing_file = /\bfile\s*,\s*file\s*,\s*file\s*,\s*file\b/i
        $keyword_stuffing_data = /\bdata\s*,\s*data\s*,\s*data\s*,\s*data\b/i
        $keyword_stuffing_code = /\bcode\s*,\s*code\s*,\s*code\s*,\s*code\b/i

        // Activation priority manipulation - TIGHTENED
        // Removed "preferred method/tool/skill" and "primary tool/skill" (very common legit language)
        // Only match explicitly coercive "use me first/before others" patterns
        $activation_priority = /\b(use (this|me) (first|before (anything|everything|other|all))|call (this|me) (before|first|instead)|priority over (all |every |other )?(tools?|skills?))\b/i

        // Impersonation patterns - TIGHTENED
        // Removed "official", "trusted", "legitimate" which are common legit descriptions
        // Only match claims that are specifically deceptive certification claims
        $trusted_impersonation = /\b(verified|certified|approved|endorsed)\s+by\s+(anthropic|openai|google|claude|microsoft)/i

        // Over-promising descriptions - RESTRUCTURED
        // Single word "perfect" is too broad. Require combination or stronger claims
        $overpromising_strong = /\b(100% (safe|secure|accurate|reliable)|guaranteed (to never|to always|that it will)|never (fails|errors|crashes|breaks)|always (works|succeeds) (perfectly|flawlessly))\b/i

        // Hidden activation triggers
        $hidden_triggers = /\b(secret (command|keyword)|hidden (feature|mode)|easter egg|backdoor (access|entry))\b/i

    condition:

        // Keyword stuffing (clear abuse)
        $keyword_stuffing_file or $keyword_stuffing_data or $keyword_stuffing_code or

        // Hidden triggers (clear abuse)
        $hidden_triggers or

        // Coercive claims require at least 2 signals to reduce FPs
        (
            ($overbroad_claims and ($activation_priority or $overpromising_strong)) or
            ($activation_priority and $overpromising_strong) or
            $trusted_impersonation
        )
}
