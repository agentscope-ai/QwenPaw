# -*- coding: utf-8 -*-
"""Cleanup script: removes all QwenPaw sandbox ACLs, profiles, users, and state.

Run on Windows:
    python scripts/cleanup_windows_sandbox.py

Administrator privileges are required for elevated sandbox cleanup (user
accounts, firewall rules, profile directories).  Unelevated and AppContainer
sandbox cleanup works without admin.

This script performs cleanup for all three sandbox backends plus deny paths:

  A. Deny paths protection (no admin required, done first):
     Reads ~/.qwenpaw/deny_paths_protection.json state file:
        1. Removes DENY ACEs for the current user from protected paths
           - Falls back to DACL reset if access denied (can't read DACL)
        2. Deletes the state JSON file

  B. AppContainer sandboxes (no admin required):
     For each metadata file in ~/.qwenpaw/containers/*.json:
        1. Removes ACLs (Win32 API) from paths in acl_manifest
        2. Deletes the AppContainer profile via userenv.dll
        3. Deletes the metadata JSON file

  C. Elevated sandboxes (requires admin):
     For each metadata file in ~/.qwenpaw/sandboxes/*.json:
        1. Removes ACLs for cap_sid and user_sid from acl_entries
           - Regular ACEs via Win32 SetNamedSecurityInfoW
           - Traverse ACEs via NtSetSecurityObject (O(1))
        2. Removes Windows Firewall block rules (netsh)
        3. Deletes the local user account (net user /delete)
        4. Removes the user profile directory (reg unload + rd /s /q)
        5. Deletes the metadata JSON file

  D. Unelevated sandboxes (no admin required):
     For each metadata file in ~/.qwenpaw/unelevated_sandboxes/*.json:
        1. Removes ACLs for cap_sid via Win32 API
           - Falls back to DACL reset if access denied
        2. Deletes the metadata JSON file
     Also migrates the legacy single state file if present.

  After all entries are processed:
     - Removes the QwenpawUsers local group (if admin, and if empty)
     - Removes empty state directories

This per-file approach allows the script to be interrupted and resumed
safely — only fully-cleaned entries have their JSON removed.

Safe to run multiple times (idempotent).
"""

import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

# ═══════════════════════════════════════════════════════════════════════════
# Win32 API ACL removal (matches sandbox code's _remove_ace_by_sid_api)
# ═══════════════════════════════════════════════════════════════════════════

# Constants
SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5


def _is_admin() -> bool:
    """Check if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def _get_state_dir() -> Path:
    """Returns the QwenPaw state directory (~/.qwenpaw)."""
    return (
        Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
        / ".qwenpaw"
    )


def _reset_dacl_to_inherited(path: str) -> bool:
    """Resets a path's DACL to inherit from parent, removing all explicit ACEs.

    This is the fallback when we cannot read the DACL (e.g. because a
    deny ACE blocks READ_CONTROL). The owner always has implicit WRITE_DAC,
    so SetNamedSecurityInfoW with a NULL DACL should succeed even when
    the DACL cannot be read.

    Setting DACL to None with UNPROTECTED_DACL_SECURITY_INFORMATION causes
    Windows to replace the DACL with inheritable ACEs from the parent.

    Returns True if the DACL was reset successfully.
    """
    try:
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    except OSError:
        return False

    info_flags = (
        DACL_SECURITY_INFORMATION | UNPROTECTED_DACL_SECURITY_INFORMATION
    )

    rc = advapi32.SetNamedSecurityInfoW(
        ctypes.c_wchar_p(path),
        SE_FILE_OBJECT,
        info_flags,
        None,
        None,
        None,  # NULL DACL = inherit from parent
        None,
    )
    if rc != ERROR_SUCCESS:
        print(
            f"    WARNING: DACL reset failed for {path}: rc={rc}",
        )
        return False

    print(f"    DACL reset to inherited for {path}")
    return True


# pylint: disable-next=too-many-branches,too-many-return-statements
def _remove_ace_by_sid_api(
    path: str,
    sid_string: str,
) -> bool:
    """Removes all ACEs matching a SID from a path's DACL using Win32 API.

    This matches the sandbox code's direct DACL manipulation approach:
    GetNamedSecurityInfoW -> enumerate ACEs -> DeleteAce ->
    SetNamedSecurityInfoW.

    If the DACL cannot be read (ERROR_ACCESS_DENIED), falls back to
    resetting the DACL to inherit from the parent directory — effectively
    removing all explicit ACEs.

    Returns True if no matching ACEs remain (success or already clean).
    Returns False on API failure.
    """
    try:
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    except OSError:
        return False

    # Convert string SID to binary SID
    target_psid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(
        ctypes.c_wchar_p(sid_string),
        ctypes.byref(target_psid),
    ):
        return False

    try:
        # Get current DACL
        p_dacl = ctypes.c_void_p()
        p_sd = ctypes.c_void_p()
        err = advapi32.GetNamedSecurityInfoW(
            ctypes.c_wchar_p(path),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(p_dacl),
            None,
            ctypes.byref(p_sd),
        )
        if err != ERROR_SUCCESS:
            # ERROR_ACCESS_DENIED: deny ACE blocks READ_CONTROL so we
            # cannot read the DACL. Fall back to resetting the DACL to
            # inherit from parent (removes ALL explicit ACEs).
            if err == ERROR_ACCESS_DENIED:
                return _reset_dacl_to_inherited(path)
            return False

        try:
            if not p_dacl.value:
                # NULL DACL means full access — no ACEs to remove
                return True

            # Get ACE count
            class ACL_SIZE_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("AceCount", ctypes.wintypes.DWORD),
                    ("AclBytesInUse", ctypes.wintypes.DWORD),
                    ("AclBytesFree", ctypes.wintypes.DWORD),
                ]

            acl_info = ACL_SIZE_INFORMATION()
            AclSizeInformation = 2
            if not advapi32.GetAclInformation(
                p_dacl,
                ctypes.byref(acl_info),
                ctypes.sizeof(acl_info),
                AclSizeInformation,
            ):
                return False

            # Find and collect indices of matching ACEs
            indices_to_delete: List[int] = []
            for i in range(acl_info.AceCount):
                ace_ptr = ctypes.c_void_p()
                if not advapi32.GetAce(p_dacl, i, ctypes.byref(ace_ptr)):
                    continue
                if ace_ptr.value is None:
                    continue

                # ACE: AceType(1) AceFlags(1) AceSize(2) Mask(4) SID
                ace_type = ctypes.cast(
                    ace_ptr,
                    ctypes.POINTER(ctypes.c_ubyte),
                )[0]
                # ACCESS_ALLOWED_ACE_TYPE=0, ACCESS_DENIED_ACE_TYPE=1
                if ace_type > 1:
                    continue

                # SID starts at offset 8
                ace_sid_ptr = ctypes.c_void_p(ace_ptr.value + 8)
                if advapi32.IsValidSid(
                    ace_sid_ptr,
                ) and advapi32.EqualSid(
                    ace_sid_ptr,
                    target_psid,
                ):
                    indices_to_delete.append(i)

            if not indices_to_delete:
                # No matching ACEs — already clean
                return True

            # Delete ACEs in reverse order to preserve indices
            for idx in reversed(indices_to_delete):
                advapi32.DeleteAce(p_dacl, idx)

            # Write back modified DACL
            err = advapi32.SetNamedSecurityInfoW(
                ctypes.c_wchar_p(path),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                p_dacl,
                None,
            )
            return err == ERROR_SUCCESS
        finally:
            ctypes.windll.kernel32.LocalFree(p_sd)  # type: ignore[attr-defined]
    finally:
        ctypes.windll.kernel32.LocalFree(target_psid)  # type: ignore[attr-defined]


def _remove_acl_with_retry(path: str, sid: str, max_attempts: int = 3) -> bool:
    """Removes ACEs for a SID with retry logic.

    Returns True if the SID was successfully removed or path doesn't exist.
    """
    if not os.path.exists(path):
        return True

    for attempt in range(1, max_attempts + 1):
        if _remove_ace_by_sid_api(path, sid):
            return True
        if attempt < max_attempts:
            time.sleep(0.5)

    return False


# ═══════════════════════════════════════════════════════════════════════════
# NtSetSecurityObject-based traverse ACE removal (elevated sandbox)
# ═══════════════════════════════════════════════════════════════════════════

# CreateFile constants
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
FILE_SHARE_ALL = 0x07
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# NtSetSecurityObject constant
DACL_SECURITY_INFORMATION_NT = 4


def _remove_traverse_ace(  # pylint: disable=R0911,R0912
    path: str,
    sid_string: str,
) -> bool:
    """Removes traverse ACEs for a SID using NtSetSecurityObject.

    This avoids the expensive inheritance propagation that
    SetNamedSecurityInfoW would trigger on directories with many children.

    Returns True if no matching ACEs remain.
    """
    try:
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll.dll", use_last_error=True)
    except OSError:
        return False

    # Convert SID string to binary
    target_psid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(
        ctypes.c_wchar_p(sid_string),
        ctypes.byref(target_psid),
    ):
        return False

    try:
        # Open directory handle with WRITE_DAC | READ_CONTROL
        handle = kernel32.CreateFileW(
            ctypes.c_wchar_p(path),
            READ_CONTROL | WRITE_DAC,
            FILE_SHARE_ALL,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle == INVALID_HANDLE_VALUE or handle is None:
            # Cannot open — try fallback via SetNamedSecurityInfoW
            return _remove_ace_by_sid_api(path, sid_string)

        try:
            # Get security info from handle
            p_dacl = ctypes.c_void_p()
            p_sd = ctypes.c_void_p()
            err = advapi32.GetSecurityInfo(
                handle,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                ctypes.byref(p_dacl),
                None,
                ctypes.byref(p_sd),
            )
            if err != ERROR_SUCCESS:
                return False

            try:
                if not p_dacl.value:
                    return True

                # Get ACE count
                class ACL_SIZE_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("AceCount", ctypes.wintypes.DWORD),
                        ("AclBytesInUse", ctypes.wintypes.DWORD),
                        ("AclBytesFree", ctypes.wintypes.DWORD),
                    ]

                acl_info = ACL_SIZE_INFORMATION()
                if not advapi32.GetAclInformation(
                    p_dacl,
                    ctypes.byref(acl_info),
                    ctypes.sizeof(acl_info),
                    2,  # AclSizeInformation
                ):
                    return False

                # Find matching ACEs
                indices_to_delete: List[int] = []
                for i in range(acl_info.AceCount):
                    ace_ptr = ctypes.c_void_p()
                    if not advapi32.GetAce(p_dacl, i, ctypes.byref(ace_ptr)):
                        continue
                    if ace_ptr.value is None:
                        continue
                    ace_sid_ptr = ctypes.c_void_p(ace_ptr.value + 8)
                    if advapi32.EqualSid(ace_sid_ptr, target_psid):
                        indices_to_delete.append(i)

                if not indices_to_delete:
                    return True

                # Delete in reverse order
                for idx in reversed(indices_to_delete):
                    advapi32.DeleteAce(p_dacl, idx)

                # Build a self-relative security descriptor with the
                # modified DACL and write via NtSetSecurityObject to
                # avoid inheritance propagation.
                sd_buf = (ctypes.c_byte * 256)()
                sd_ptr = ctypes.cast(sd_buf, ctypes.c_void_p)
                advapi32.InitializeSecurityDescriptor(
                    sd_ptr,
                    1,  # SECURITY_DESCRIPTOR_REVISION
                )
                advapi32.SetSecurityDescriptorDacl(
                    sd_ptr,
                    True,
                    p_dacl,
                    False,
                )

                # Make self-relative
                sr_size = ctypes.wintypes.DWORD(0)
                advapi32.MakeSelfRelativeSD(
                    sd_ptr,
                    None,
                    ctypes.byref(sr_size),
                )
                sr_buf = (ctypes.c_byte * sr_size.value)()
                sr_ptr = ctypes.cast(sr_buf, ctypes.c_void_p)
                if not advapi32.MakeSelfRelativeSD(
                    sd_ptr,
                    sr_ptr,
                    ctypes.byref(sr_size),
                ):
                    # Fallback to SetNamedSecurityInfoW
                    err = advapi32.SetNamedSecurityInfoW(
                        ctypes.c_wchar_p(path),
                        SE_FILE_OBJECT,
                        DACL_SECURITY_INFORMATION,
                        None,
                        None,
                        p_dacl,
                        None,
                    )
                    return err == ERROR_SUCCESS

                # NtSetSecurityObject(Handle, SecurityInformation, SD)
                ntstatus = ntdll.NtSetSecurityObject(
                    handle,
                    DACL_SECURITY_INFORMATION_NT,
                    sr_ptr,
                )
                return ntstatus == 0  # STATUS_SUCCESS

            finally:
                ctypes.windll.kernel32.LocalFree(p_sd)  # type: ignore[attr-defined]
        finally:
            kernel32.CloseHandle(handle)
    finally:
        ctypes.windll.kernel32.LocalFree(target_psid)  # type: ignore[attr-defined]


# ═══════════════════════════════════════════════════════════════════════════
# System command helpers
# ═══════════════════════════════════════════════════════════════════════════


def _run_cmd(
    args: List[str],
    timeout: int = 60,
) -> Optional[subprocess.CompletedProcess]:
    """Runs a command synchronously. Returns result or None on failure."""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def _delete_appcontainer_profile(container_name: str) -> bool:
    """Deletes an AppContainer profile by name."""
    try:
        userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        hr = userenv.DeleteAppContainerProfile(
            ctypes.c_wchar_p(container_name),
        )
        return hr == 0
    except OSError:
        return False


def _remove_firewall_rules(username: str) -> bool:
    """Removes inbound/outbound firewall block rules for a sandbox user."""
    rule_name_out = f"QwenPaw_Block_{username}_Out"
    rule_name_in = f"QwenPaw_Block_{username}_In"
    ok = True
    for rule_name in (rule_name_out, rule_name_in):
        result = _run_cmd(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "delete",
                "rule",
                f"name={rule_name}",
            ],
            timeout=15,
        )
        if result is None:
            ok = False
    return ok


def _delete_local_user(username: str) -> bool:
    """Deletes a local Windows user account."""
    result = _run_cmd(["net", "user", username, "/delete"], timeout=30)
    return result is not None and result.returncode == 0


def _delete_local_group(group_name: str) -> bool:
    """Deletes a local Windows group."""
    result = _run_cmd(
        ["net", "localgroup", group_name, "/delete"],
        timeout=30,
    )
    return result is not None and result.returncode == 0


def _remove_profile_dir(username: str, user_sid: str = "") -> bool:
    """Removes the sandbox user's profile directory.

    Uses reg unload (to release NTUSER.DAT lock) + rd /s /q (fast
    kernel-mode delete). Falls back to takeown + retry on failure.
    """
    sys_drive = os.environ.get("SystemDrive", "C:")
    profile_dir = os.path.join(sys_drive + os.sep, "Users", username)
    if not os.path.exists(profile_dir):
        return True

    # Unload the user's registry hive to release NTUSER.DAT lock
    if user_sid:
        _run_cmd(["reg", "unload", f"HKU\\{user_sid}"], timeout=15)

    # Fast kernel-mode recursive delete
    _run_cmd(["cmd", "/c", "rd", "/s", "/q", profile_dir], timeout=60)

    if not os.path.exists(profile_dir):
        return True

    # Fallback: take ownership recursively then retry
    _run_cmd(
        ["takeown", "/F", profile_dir, "/R", "/A", "/D", "Y"],
        timeout=120,
    )
    _run_cmd(["cmd", "/c", "rd", "/s", "/q", profile_dir], timeout=60)

    if os.path.exists(profile_dir):
        print(
            f"    WARNING: Profile dir {profile_dir} could not be fully "
            f"removed. Manual intervention may be required.",
        )
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
# AppContainer sandbox cleanup
# ═══════════════════════════════════════════════════════════════════════════


def _cleanup_single_container(  # pylint: disable=R0912
    meta_file: Path,
) -> None:
    """Clean up a single AppContainer sandbox.

    Steps: Remove ACLs -> Delete profile -> Delete metadata.
    """
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"\n  WARNING: Cannot read {meta_file.name}: {e}")
        try:
            meta_file.unlink()
        except OSError:
            pass
        return

    container_name = meta.get("container_name", "")
    sid = meta.get("sid", "")
    workspace_dir = meta.get("workspace_dir", "")
    acl_manifest = meta.get("acl_manifest")

    print(f"\n  Container: {container_name}")
    print(f"    SID: {sid}")

    # Step 1: Remove ACL entries
    acl_removed = 0
    acl_failed = 0
    if sid:
        if acl_manifest:
            all_paths = (
                acl_manifest.get("grant_paths", [])
                + acl_manifest.get("deny_paths", [])
                + acl_manifest.get("inheritance_broken_paths", [])
            )
            for path in all_paths:
                if path and os.path.exists(path):
                    if _remove_acl_with_retry(path, sid):
                        acl_removed += 1
                    else:
                        acl_failed += 1
                        print(f"    FAILED to remove ACL from: {path}")

        if workspace_dir and os.path.exists(workspace_dir):
            if _remove_acl_with_retry(workspace_dir, sid):
                acl_removed += 1
            else:
                acl_failed += 1
                print(
                    f"    FAILED to remove ACL from workspace: {workspace_dir}",
                )

    if acl_removed or acl_failed:
        print(f"    ACLs: {acl_removed} removed, {acl_failed} failed")

    # Step 2: Delete the AppContainer profile
    if container_name:
        ok = _delete_appcontainer_profile(container_name)
        print(f"    Profile: {'deleted' if ok else 'not found or failed'}")

    # Step 3: Handle metadata file
    if acl_failed > 0:
        _move_to_failed(
            meta_file,
            _get_state_dir(),
            f"ACL removal failed for {acl_failed} path(s)",
        )
    else:
        try:
            meta_file.unlink()
            print("    Metadata: deleted")
        except OSError as e:
            print(f"    WARNING: Failed to delete {meta_file.name}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Elevated sandbox cleanup
# ═══════════════════════════════════════════════════════════════════════════


def _cleanup_single_elevated_sandbox(  # pylint: disable=R0912,R0915
    meta_file: Path,
) -> None:
    """Clean up a single elevated sandbox.

    Steps:
        1. Remove ACLs (Win32 API for regular, NtSetSecurityObject for traverse)
        2. Remove firewall rules
        3. Delete local user account
        4. Remove user profile directory
        5. Delete metadata
    """
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"\n  WARNING: Cannot read {meta_file.name}: {e}")
        try:
            meta_file.unlink()
        except OSError:
            pass
        return

    sandbox_id = meta.get("sandbox_id", "")
    username = meta.get("username", "")
    user_sid = meta.get("user_sid", "")
    cap_sid = meta.get("cap_sid", "")
    network_blocked = meta.get("network_blocked", False)
    acl_entries = meta.get("acl_entries", [])

    print(f"\n  Elevated Sandbox: {sandbox_id}")
    print(f"    Username: {username}")
    print(f"    User SID: {user_sid}")
    print(f"    Cap SID:  {cap_sid}")

    # Step 1: Remove ACL entries
    acl_removed = 0
    acl_failed = 0
    if acl_entries:
        print(f"    Processing {len(acl_entries)} ACL entries...")
        for entry in acl_entries:
            entry_path = entry.get("path", "")
            sid_type = entry.get("sid_type", "")
            access_mode = entry.get("access_mode", "")

            if not entry_path or not os.path.exists(entry_path):
                continue

            # Determine which SID was used
            if sid_type == "cap":
                sid = cap_sid
            elif sid_type == "user":
                sid = user_sid
            elif sid_type == "group":
                # QwenpawUsers group ACEs are persistent — skip
                continue
            else:
                continue

            if not sid:
                continue

            # Use appropriate removal method
            if access_mode == "traverse":
                ok = _remove_traverse_ace(entry_path, sid)
            else:
                ok = _remove_acl_with_retry(entry_path, sid)

            if ok:
                acl_removed += 1
            else:
                acl_failed += 1
                print(f"    FAILED: {entry_path} ({sid_type}, {access_mode})")

    if acl_removed or acl_failed:
        print(f"    ACLs: {acl_removed} removed, {acl_failed} failed")

    # Step 2: Remove firewall rules
    firewall_failed = False
    if network_blocked and username:
        ok = _remove_firewall_rules(username)
        if not ok:
            firewall_failed = True
        print(
            f"    Firewall: {'removed' if ok else 'removal failed (may not exist)'}",
        )

    # Step 3: Delete the local user account
    user_failed = False
    if username:
        ok = _delete_local_user(username)
        if not ok:
            user_failed = True
        print(
            f"    User account: {'deleted' if ok else 'deletion failed (may not exist)'}",
        )

    # Step 4: Remove user profile directory
    profile_failed = False
    if username:
        ok = _remove_profile_dir(username, user_sid)
        if not ok:
            profile_failed = True
        print(f"    Profile dir: {'removed' if ok else 'removal failed'}")

    # Step 5: Handle metadata file
    failures: List[str] = []
    if acl_failed > 0:
        failures.append(f"ACL removal failed for {acl_failed} path(s)")
    if firewall_failed:
        failures.append("firewall rule removal failed")
    if user_failed:
        failures.append("user account deletion failed")
    if profile_failed:
        failures.append("profile directory removal failed")

    if failures:
        _move_to_failed(
            meta_file,
            _get_state_dir(),
            "; ".join(failures),
        )
    else:
        try:
            meta_file.unlink()
            print("    Metadata: deleted")
        except OSError as e:
            print(f"    WARNING: Failed to delete {meta_file.name}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Unelevated sandbox cleanup (no admin required)
# ═══════════════════════════════════════════════════════════════════════════


def _cleanup_single_unelevated_sandbox(meta_file: Path) -> None:
    """Clean up a single unelevated sandbox.

    Steps: Remove ACLs -> Delete metadata.
    """
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"\n  WARNING: Cannot read {meta_file.name}: {e}")
        try:
            meta_file.unlink()
        except OSError:
            pass
        return

    sandbox_id = meta.get("sandbox_id", "")
    cap_sid = meta.get("cap_sid", "")
    acl_entries = meta.get("acl_entries", [])

    print(f"\n  Unelevated Sandbox: {sandbox_id}")
    print(f"    Cap SID: {cap_sid}")

    # Step 1: Remove ACL entries
    acl_removed = 0
    acl_failed = 0
    if acl_entries and cap_sid:
        for entry in acl_entries:
            entry_path = entry.get("path", "")
            if not entry_path or not os.path.exists(entry_path):
                continue
            if _remove_acl_with_retry(entry_path, cap_sid):
                acl_removed += 1
            else:
                acl_failed += 1
                print(f"    FAILED to remove ACL from: {entry_path}")

    if acl_removed or acl_failed:
        print(f"    ACLs: {acl_removed} removed, {acl_failed} failed")

    # Step 2: Handle metadata file
    if acl_failed > 0:
        _move_to_failed(
            meta_file,
            _get_state_dir(),
            f"ACL removal failed for {acl_failed} path(s)",
        )
    else:
        try:
            meta_file.unlink()
            print("    Metadata: deleted")
        except OSError as e:
            print(f"    WARNING: Failed to delete {meta_file.name}: {e}")


def _migrate_legacy_state_file(state_dir: Path) -> None:
    """Removes the legacy single unelevated sandbox state file."""
    legacy_file = state_dir / "unelevated_sandbox_state.json"
    if not legacy_file.exists():
        return
    print("  Migrating legacy unelevated state file...")
    try:
        state = json.loads(legacy_file.read_text(encoding="utf-8"))
        cap_sid = state.get("cap_sid", "")
        if cap_sid:
            all_paths = state.get("acl_paths", []) + state.get(
                "deny_paths",
                [],
            )
            for path in all_paths:
                if os.path.exists(path):
                    _remove_acl_with_retry(path, cap_sid)
        legacy_file.unlink(missing_ok=True)
        print("  Legacy state file removed.")
    except (json.JSONDecodeError, OSError) as e:
        print(f"  WARNING: Failed to migrate legacy state: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Deny Paths Protection cleanup (no admin required)
# ═══════════════════════════════════════════════════════════════════════════


def _get_current_user_sid_string() -> Optional[str]:
    """Gets the current user's SID string."""
    try:
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    except OSError:
        return None

    # OpenProcessToken
    token = ctypes.c_void_p()
    TOKEN_QUERY = 0x0008
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_QUERY,
        ctypes.byref(token),
    ):
        return None

    try:
        # GetTokenInformation for TokenUser
        TokenUser = 1
        buf_size = ctypes.wintypes.DWORD(0)
        advapi32.GetTokenInformation(
            token,
            TokenUser,
            None,
            0,
            ctypes.byref(buf_size),
        )
        buf = (ctypes.c_byte * buf_size.value)()
        if not advapi32.GetTokenInformation(
            token,
            TokenUser,
            ctypes.byref(buf),
            buf_size.value,
            ctypes.byref(buf_size),
        ):
            return None

        # TOKEN_USER structure: first field is PSID
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]

        # ConvertSidToStringSidW
        sid_str_ptr = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(
            ctypes.c_void_p(psid),
            ctypes.byref(sid_str_ptr),
        ):
            return None

        try:
            return sid_str_ptr.value
        finally:
            kernel32.LocalFree(sid_str_ptr)
    finally:
        kernel32.CloseHandle(token)


def _cleanup_deny_paths_protection(  # pylint: disable=R0912
    state_dir: Path,
) -> None:
    """Cleans up deny paths protection ACLs and state file.

    Reads the deny_paths_protection.json state file and removes any
    DENY ACEs that were set on the current user for protected paths.
    This matches the DenyPathsProtection.disable() + cleanup_orphaned()
    logic in the sandbox code.
    """
    state_file = state_dir / "deny_paths_protection.json"
    if not state_file.exists():
        print("    No deny paths state file found.")
        return

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"    WARNING: Cannot read deny paths state: {e}")
        try:
            state_file.unlink(missing_ok=True)
        except OSError:
            pass
        return

    if not state.get("active"):
        print("    Deny paths protection is not active.")
        try:
            state_file.unlink(missing_ok=True)
        except OSError:
            pass
        return

    user_sid = state.get("user_sid", "")
    paths = state.get("protected_paths", [])

    if not user_sid:
        # Try to get current user SID as fallback
        user_sid = _get_current_user_sid_string() or ""

    if not user_sid:
        print("    WARNING: Cannot determine user SID for cleanup.")
        return

    print(f"    User SID: {user_sid}")
    print(f"    Protected paths: {len(paths)}")

    succeeded = 0
    failed = 0
    for path in paths:
        if not os.path.exists(path):
            succeeded += 1
            continue
        if _remove_acl_with_retry(path, user_sid):
            succeeded += 1
            print(f"    Removed deny ACL from: {path}")
        else:
            failed += 1
            print(f"    FAILED to remove deny ACL from: {path}")

    if succeeded or failed:
        print(f"    Results: {succeeded} cleaned, {failed} failed")

    # Remove state file
    try:
        state_file.unlink(missing_ok=True)
        print("    State file: deleted")
    except OSError as e:
        print(f"    WARNING: Failed to delete state file: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# QwenpawUsers group cleanup (elevated only)
# ═══════════════════════════════════════════════════════════════════════════


def _cleanup_sandbox_group() -> None:
    """Removes the QwenpawUsers local group and associated markers."""
    print("\n  Removing QwenpawUsers group...")
    ok = _delete_local_group("QwenpawUsers")
    if ok:
        print("    Group deleted.")
    else:
        print("    Group deletion failed (may not exist or not empty).")

    # Remove the .qwenpaw_acl_granted marker from the Python directory.
    # Without this, next sandbox creation would see the stale marker and
    # skip re-granting the ACL to the (re-created) group.
    python_dir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.basename(python_dir).lower() == "scripts":
        python_dir = os.path.dirname(python_dir)

    marker = os.path.join(python_dir, ".qwenpaw_acl_granted")
    if os.path.exists(marker):
        try:
            os.remove(marker)
            print(f"    Removed ACL marker: {marker}")
        except OSError as e:
            print(f"    WARNING: Failed to remove marker: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Failed cleanup metadata preservation
# ═══════════════════════════════════════════════════════════════════════════


def _move_to_failed(
    meta_file: Path,
    state_dir: Path,
    reason: str,
) -> None:
    """Moves a metadata file to failed_cleanup/ for later retry.

    Appends a ``_cleanup_error`` field with failure reason and timestamp
    so the user knows what went wrong.
    """
    import datetime

    failed_dir = state_dir / "failed_cleanup"
    failed_dir.mkdir(parents=True, exist_ok=True)

    dest = failed_dir / meta_file.name
    # If a file with the same name already exists, append a counter
    counter = 1
    while dest.exists():
        stem = meta_file.stem
        dest = failed_dir / f"{stem}_{counter}.json"
        counter += 1

    # Read, annotate, and write to new location
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        meta = {}

    meta["_cleanup_error"] = {
        "reason": reason,
        "timestamp": datetime.datetime.now().isoformat(),
    }

    try:
        dest.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"    ERROR: Cannot save failed metadata to {dest}: {e}")
        return

    # Remove the original
    try:
        meta_file.unlink()
    except OSError:
        pass

    print(f"    Metadata preserved in: {dest.name} (for retry)")


# ═══════════════════════════════════════════════════════════════════════════
# Orchestration
# ═══════════════════════════════════════════════════════════════════════════


def _count_json(directory: Path) -> int:
    """Count *.json files in a directory (0 if doesn't exist)."""
    if directory.is_dir():
        return len(list(directory.glob("*.json")))
    return 0


def _confirm_cleanup(
    is_admin: bool,
    appcontainer_count: int,
    elevated_count: int,
    unelevated_count: int,
    deny_paths_active: bool,
) -> None:
    """Print summary and prompt user for confirmation."""
    print("=" * 60)
    print("WARNING: This will clean up ALL QwenPaw sandboxes,")
    print("including any that are currently RUNNING.")
    print()
    print(f"  AppContainer sandboxes:    {appcontainer_count}")
    print(f"  Elevated sandboxes:        {elevated_count}")
    print(f"  Unelevated sandboxes:      {unelevated_count}")
    print(
        f"  Deny paths protection:     "
        f"{'ACTIVE' if deny_paths_active else 'inactive'}",
    )
    if not is_admin and elevated_count:
        print()
        print(
            "  NOTE: Not running as administrator. Elevated sandbox",
        )
        print(
            "  cleanup will be SKIPPED (user accounts, firewall, profiles).",
        )
    print()
    print("The following actions will be performed:")
    print("  - Remove filesystem ACLs set by sandboxes (Win32 API)")
    if is_admin:
        print("  - Delete AppContainer profiles")
        print("  - Delete local sandbox user accounts (qwenpaw_*)")
        print("  - Remove firewall block rules")
        print("  - Remove user profile directories")
        print("  - Remove QwenpawUsers group (if empty)")
    else:
        print("  - Delete AppContainer profiles")
    if deny_paths_active:
        print("  - Remove deny path ACLs (current user DENY ACEs)")
    print("  - Delete sandbox metadata files")
    print()
    print("Please make sure no sandbox is currently in use.")
    print("=" * 60)
    print()
    choice = input("Continue? (Y/N): ").strip().upper()
    if choice != "Y":
        print("Aborted.")
        sys.exit(0)
    print()


def _cleanup_state_dirs(state_dir: Path, *, is_admin: bool) -> None:
    """Remove empty state directories after cleanup."""
    unelevated_dir = state_dir / "unelevated_sandboxes"
    containers_dir = state_dir / "containers"
    sandboxes_dir = state_dir / "sandboxes"
    failed_dir = state_dir / "failed_cleanup"

    dirs_to_check = [unelevated_dir, containers_dir]
    if is_admin:
        dirs_to_check.append(sandboxes_dir)

    for d in dirs_to_check:
        if d.is_dir() and not list(d.iterdir()):
            try:
                d.rmdir()
                print(f"  Removed empty dir: {d.name}/")
            except OSError:
                pass

    # Report failed_cleanup contents (never auto-delete)
    if failed_dir.is_dir():
        failed_files = list(failed_dir.iterdir())
        if failed_files:
            print(
                f"  WARNING: {len(failed_files)} metadata file(s) in "
                f"failed_cleanup/ — re-run script to retry or "
                f"delete manually.",
            )

    # Remove root state dir if completely empty
    if state_dir.is_dir():
        remaining = list(state_dir.iterdir())
        if not remaining:
            try:
                state_dir.rmdir()
                print(f"  Removed empty state dir: {state_dir}")
            except OSError:
                pass
        else:
            print(
                f"  State dir not empty, remaining: "
                f"{[e.name for e in remaining]}",
            )


def main() -> None:  # pylint: disable=R0912,R0915
    if sys.platform != "win32":
        print("ERROR: This script must run on Windows.")
        sys.exit(1)

    is_admin = _is_admin()

    state_dir = _get_state_dir()
    containers_dir = state_dir / "containers"
    sandboxes_dir = state_dir / "sandboxes"
    unelevated_dir = state_dir / "unelevated_sandboxes"
    deny_paths_state = state_dir / "deny_paths_protection.json"

    appcontainer_count = _count_json(containers_dir)
    elevated_count = _count_json(sandboxes_dir)
    unelevated_count = _count_json(unelevated_dir)

    # Check deny paths protection state
    deny_paths_active = False
    if deny_paths_state.exists():
        try:
            dp_state = json.loads(
                deny_paths_state.read_text(encoding="utf-8"),
            )
            deny_paths_active = dp_state.get("active", False)
        except (json.JSONDecodeError, OSError):
            pass

    has_work = (
        appcontainer_count
        or elevated_count
        or unelevated_count
        or deny_paths_active
        or deny_paths_state.exists()
    )
    if not has_work:
        # Check for legacy state file
        legacy = state_dir / "unelevated_sandbox_state.json"
        if not legacy.exists():
            print(
                "No QwenPaw sandbox metadata found. Nothing to clean up.",
            )
            sys.exit(0)

    _confirm_cleanup(
        is_admin,
        appcontainer_count,
        elevated_count,
        unelevated_count,
        deny_paths_active,
    )

    print("=" * 60)
    print("QwenPaw Sandbox Cleanup")
    print("=" * 60)
    print(f"  State directory: {state_dir}")
    if not is_admin:
        print("  Running without admin — elevated sandbox cleanup skipped")
    print()

    # Step 1: Deny paths protection (no admin required, do first so
    # files are accessible for subsequent steps)
    print("[1] Deny paths protection")
    _cleanup_deny_paths_protection(state_dir)

    # Step 2: AppContainer sandboxes (no admin required)
    print(f"\n[2] AppContainer sandboxes ({appcontainer_count} found)")
    if containers_dir.is_dir():
        for meta_file in sorted(containers_dir.glob("*.json")):
            _cleanup_single_container(meta_file)
    if not appcontainer_count:
        print("    Nothing to clean.")

    # Step 3: Elevated sandboxes (admin required)
    print(f"\n[3] Elevated sandboxes ({elevated_count} found)")
    if is_admin:
        if sandboxes_dir.is_dir():
            for meta_file in sorted(sandboxes_dir.glob("*.json")):
                _cleanup_single_elevated_sandbox(meta_file)
        if not elevated_count:
            print("    Nothing to clean.")
        # Clean up QwenpawUsers group after all elevated sandboxes are removed
        if elevated_count > 0:
            _cleanup_sandbox_group()
    else:
        if elevated_count:
            print("    SKIPPED (requires administrator privileges)")
        else:
            print("    Nothing to clean.")

    # Step 4: Unelevated sandboxes (no admin required)
    print(f"\n[4] Unelevated sandboxes ({unelevated_count} found)")
    _migrate_legacy_state_file(state_dir)
    if unelevated_dir.is_dir():
        for meta_file in sorted(unelevated_dir.glob("*.json")):
            _cleanup_single_unelevated_sandbox(meta_file)
    if not unelevated_count:
        print("    Nothing to clean.")

    # Step 5: Clean up empty directories
    print("\n[5] Cleaning up state directories...")
    _cleanup_state_dirs(state_dir, is_admin=is_admin)

    print("\n" + "=" * 60)
    print("Cleanup complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
