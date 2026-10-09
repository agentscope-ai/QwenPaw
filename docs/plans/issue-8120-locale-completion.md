# Issue #8120: complete chunk-error translations

## Agreed scope

Complete the current chunk recovery and diagnostics strings for all seven
supported Console languages. Add the missing Japanese, Russian, Brazilian
Portuguese, Indonesian, and Vietnamese translations. Translate the remaining
English text in the Brazilian Portuguese chunk-error section.

## Checklist

- [x] Identify supported languages and missing chunk-error strings.
- [x] Complete translations, preserving diagnostic field names and meaning.
- [x] Verify JSON, matching keys, nonempty translations, and formatting.
- [x] Run the existing language-loading tests.

## Verification

- All seven supported locales have the same 19 chunk-error translation keys.
- All strings are nonempty; non-English locales have no English fallbacks in
  this section. Diagnostic field names and DNS/TLS/CORS terms are preserved.
- All nine existing i18n tests passed. Prettier and git diff checks passed.
