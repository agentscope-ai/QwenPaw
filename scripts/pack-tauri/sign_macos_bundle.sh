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

is_inside_framework() {
    [[ "$1" == *".framework/"* ]]
}

is_python_framework_main_executable() {
    local path="$1"
    local dir

    if [[ "$(basename "${path}")" != "Python" ]]; then
        return 1
    fi

    dir="$(dirname "${path}")"
    [[ -f "${dir}/Resources/Info.plist" ]]
}

find_python_framework_version_dirs() {
    local python_path
    local dir

    while IFS= read -r python_path; do
        if is_inside_framework "${python_path}"; then
            continue
        fi

        dir="$(dirname "${python_path}")"
        if [[ -f "${dir}/Resources/Info.plist" ]] && is_macho "${python_path}"; then
            printf '%s\n' "${dir}"
        fi
    done < <(find "${TARGET}" -type f -name "Python" | sort -r)
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

echo "Signing macOS native files in ${TARGET}"
echo "Signing identity: ${IDENTITY}"

signed_files=0
while IFS= read -r -d '' path; do
    if is_inside_framework "${path}"; then
        continue
    fi
    if is_python_framework_main_executable "${path}"; then
        continue
    fi
    if is_macho "${path}"; then
        codesign_file "${path}"
        signed_files=$((signed_files + 1))
    fi
done < <(find "${TARGET}" -type f -print0)

# Bundle containers carry their own resource seal. Sign nested code first,
# then sign containers from the inside out, and sign the outer app last.
signed_frameworks=0
while IFS= read -r framework; do
    if [[ -n "${framework}" ]]; then
        codesign_bundle "${framework}"
        signed_frameworks=$((signed_frameworks + 1))
    fi
done < <(find "${TARGET}" -type d -name "*.framework" | sort -r)

signed_apps=0
while IFS= read -r app_bundle; do
    if [[ -n "${app_bundle}" && "${app_bundle}" != "${TARGET}" ]]; then
        codesign_bundle "${app_bundle}"
        signed_apps=$((signed_apps + 1))
    fi
done < <(find "${TARGET}" -type d -name "*.app" | sort -r)

# The CPython framework version directory is copied as python-runtime on macOS.
# Its directory name no longer ends in .framework, but Resources/Info.plist and
# the Python executable still make it a signed bundle container.
signed_python_bundles=0
while IFS= read -r python_bundle; do
    if [[ -n "${python_bundle}" ]]; then
        codesign_bundle "${python_bundle}"
        signed_python_bundles=$((signed_python_bundles + 1))
    fi
done < <(find_python_framework_version_dirs)

if [[ "${TARGET}" == *.app ]]; then
    codesign_bundle "${TARGET}"
fi

echo "Signed ${signed_files} Mach-O files, ${signed_frameworks} frameworks, ${signed_apps} apps, and ${signed_python_bundles} Python bundles"

if [[ "${TARGET}" == *.app ]]; then
    codesign --verify --deep --strict --verbose=2 "${TARGET}"
else
    while IFS= read -r -d '' path; do
        if is_inside_framework "${path}"; then
            continue
        fi
        if is_python_framework_main_executable "${path}"; then
            continue
        fi
        if is_macho "${path}"; then
            codesign --verify --verbose=2 "${path}"
        fi
    done < <(find "${TARGET}" -type f -print0)
    while IFS= read -r framework; do
        if [[ -n "${framework}" ]]; then
            codesign --verify --verbose=2 "${framework}"
        fi
    done < <(find "${TARGET}" -type d -name "*.framework" | sort -r)
    while IFS= read -r app_bundle; do
        if [[ -n "${app_bundle}" && "${app_bundle}" != "${TARGET}" ]]; then
            codesign --verify --verbose=2 "${app_bundle}"
        fi
    done < <(find "${TARGET}" -type d -name "*.app" | sort -r)
    while IFS= read -r python_bundle; do
        if [[ -n "${python_bundle}" ]]; then
            codesign --verify --verbose=2 "${python_bundle}"
        fi
    done < <(find_python_framework_version_dirs)
fi
