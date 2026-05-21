#!/usr/bin/env bash
# Re-sign all Mach-O files in a macOS bundle/directory with one identity.
#
# PyInstaller collects Python frameworks and native extension libraries from
# third-party packages. Re-signing every Mach-O file after collection keeps the
# backend executable, Python runtime, and native dependencies in one signature
# state before Tauri embeds them in the final app.

set -euo pipefail

TARGET="${1:?Usage: sign_macos_bundle.sh <target> [identity]}"
IDENTITY="${2:-${APPLE_SIGNING_IDENTITY:--}}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: macOS code signing must run on Darwin"
    exit 1
fi

if ! command -v codesign >/dev/null 2>&1; then
    echo "ERROR: codesign not found"
    exit 1
fi

if ! command -v file >/dev/null 2>&1; then
    echo "ERROR: file not found"
    exit 1
fi

if [[ ! -e "${TARGET}" ]]; then
    echo "ERROR: signing target not found: ${TARGET}"
    exit 1
fi

signing_args() {
    printf '%s\n' --force --sign "${IDENTITY}"
    if [[ "${IDENTITY}" == "-" ]]; then
        printf '%s\n' --timestamp=none
    fi
}

is_macho() {
    file -b "$1" | grep -q "Mach-O"
}

codesign_file() {
    local path="$1"
    local args=()
    local arg

    while IFS= read -r arg; do
        args+=("${arg}")
    done < <(signing_args)

    codesign "${args[@]}" "${path}"
}

codesign_bundle() {
    local path="$1"
    local args=()
    local arg

    while IFS= read -r arg; do
        args+=("${arg}")
    done < <(signing_args)

    codesign "${args[@]}" "${path}"
}

try_codesign_framework() {
    local path="$1"
    local output

    if output=$(codesign_bundle "${path}" 2>&1); then
        return 0
    fi

    # PyInstaller may collect framework-looking directories that are not valid
    # framework bundles. Their Mach-O files are still signed individually below.
    if grep -q "bundle format is ambiguous" <<<"${output}"; then
        echo "Skipping framework bundle signature for ${path}: ${output}"
        return 2
    fi

    echo "${output}" >&2
    return 1
}

verify_macho_files() {
    local path

    while IFS= read -r -d '' path; do
        if is_macho "${path}"; then
            codesign --verify --verbose=2 "${path}"
        fi
    done < <(find "${TARGET}" -type f -print0)
}

verify_framework_bundles() {
    local framework
    local output

    while IFS= read -r framework; do
        if [[ -z "${framework}" ]]; then
            continue
        fi
        if ! output=$(codesign --verify --verbose=2 "${framework}" 2>&1); then
            if grep -q "bundle format is ambiguous" <<<"${output}"; then
                echo "Skipping framework bundle verification for ${framework}: ${output}"
            else
                echo "${output}" >&2
                exit 1
            fi
        fi
    done < <(find "${TARGET}" -type d -name "*.framework" | sort -r)
}

echo "Signing macOS native files in ${TARGET}"
echo "Signing identity: ${IDENTITY}"

signed_files=0
while IFS= read -r -d '' path; do
    if is_macho "${path}"; then
        codesign_file "${path}"
        signed_files=$((signed_files + 1))
    fi
done < <(find "${TARGET}" -type f -print0)

# Framework directories carry their own bundle signature. Sign them after the
# contained Mach-O files, then sign the app bundle last.
signed_frameworks=0
skipped_frameworks=0
while IFS= read -r framework; do
    if [[ -n "${framework}" ]]; then
        if try_codesign_framework "${framework}"; then
            signed_frameworks=$((signed_frameworks + 1))
        else
            status=$?
            if [[ "${status}" -eq 2 ]]; then
                skipped_frameworks=$((skipped_frameworks + 1))
            else
                exit "${status}"
            fi
        fi
    fi
done < <(find "${TARGET}" -type d -name "*.framework" | sort -r)

if [[ "${TARGET}" == *.app ]]; then
    codesign_bundle "${TARGET}"
fi

echo "Signed ${signed_files} Mach-O files and ${signed_frameworks} frameworks"
if [[ "${skipped_frameworks}" -gt 0 ]]; then
    echo "Skipped ${skipped_frameworks} framework-looking directories; their Mach-O files were signed individually"
fi

if [[ "${TARGET}" == *.app ]]; then
    verify_macho_files
    verify_framework_bundles
    codesign --verify --strict --verbose=2 "${TARGET}"
else
    verify_macho_files
    verify_framework_bundles
fi
