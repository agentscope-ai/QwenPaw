//////////////////////////////////////////
// Unicode Steganography and Hidden Characters Detection
// Target: Invisible Unicode used for prompt injection
// Based on: https://en.wikipedia.org/wiki/Tags_(Unicode_block)
// Tuned to reduce FPs: requires high threshold OR dangerous code context
//////////////////////////////////////////

rule prompt_injection_unicode_steganography{

    meta:
        author = "Cisco"
        description = "Detects hidden Unicode characters used for invisible prompt injection and steganography"
        classification = "harmful"
        threat_type = "UNICODE STEGANOGRAPHY"
        reference = "https://en.wikipedia.org/wiki/Tags_(Unicode_block)"

    strings:

        // --- 1. Unicode Tag Regex Patterns ---
        // Catches \uE00xx, \u{E00xx}, and \U000E00xx encoding styles
        $unicode_tag_pattern = /\\u(\{)?[Ee]00[0-7][0-9A-Fa-f](\})?/
        $unicode_long_tag = /\\U000[Ee]00[0-7][0-9A-Fa-f]/

        // --- 2. Zero-width characters (steganography) ---
        // UTF-8 hex encoding
        $zw_space = "\xE2\x80\x8B"  // U+200B ZERO WIDTH SPACE
        $zw_non_joiner = "\xE2\x80\x8C"  // U+200C
        $zw_joiner = "\xE2\x80\x8D"  // U+200D

        // --- 3. Directional Overrides (text spoofing) ---
        $rtlo = "\xE2\x80\xAE"  // U+202E RIGHT-TO-LEFT OVERRIDE
        $ltro = "\xE2\x80\xAD"  // U+202D LEFT-TO-RIGHT OVERRIDE

        // --- 4. Invisible separators ---
        $line_separator = "\xE2\x80\xA8"  // U+2028 LINE SEPARATOR
        $paragraph_separator = "\xE2\x80\xA9"  // U+2029 PARAGRAPH SEPARATOR

        // --- 5. Variation Selectors Supplement (U+E0100-E01EF) ---
        // Used in os-info-checker-es6 attack (2025)
        $var_selectors = { F3 A0 (84|85|86|87) }

        // --- 6. Dangerous code patterns (context for zero-width detection) ---
        $eval_decode = /eval\s*\(\s*(atob|unescape)\s*\(/
        $func_decode = /Function\s*\(\s*atob\s*\(/
        $fromcharcode = /String\.fromCharCode/

    condition:
        (
            // Encoded tag characters in strings (always suspicious)
            $unicode_tag_pattern or
            $unicode_long_tag or

            // Variation selectors + decode = highly suspicious (os-info-checker-es6 pattern)
            (#var_selectors > 5 and any of ($eval_decode, $func_decode, $fromcharcode)) or

            // Zero-width steganography requires BOTH high count AND suspicious code
            // 50+ zero-width chars + decode function = likely steganography
            ((#zw_space + #zw_non_joiner + #zw_joiner) > 50 and any of ($eval_decode, $func_decode, $fromcharcode)) or

            // Very high zero-width count alone is suspicious (>200 indicates deliberate encoding)
            (#zw_space + #zw_non_joiner + #zw_joiner) > 200 or

            // Any directional override (highly suspicious in source code)
            $rtlo or
            $ltro or

            // Invisible separators (no legitimate use in source code)
            $line_separator or
            $paragraph_separator
        )
}
