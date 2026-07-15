# -*- coding: utf-8 -*-
"""Cleanup script: removes all QwenPaw sandbox profiles, ACLs, users, and state.

Run on Windows with administrator privileges:
    python scripts/cleanup_windows_sandbox.py

This script performs cleanup for BOTH sandbox backends:

  A. AppContainer sandboxes (allow_read_all=False):
     For each container metadata file in ~/.qwenpaw/containers/*.json:
        1. Removes ACLs (icacls /remove) from known paths
        2. Removes the associated NTFS junction
        3. Deletes the AppContainer profile via userenv.dll
        4. Deletes the metadata JSON file

  B. Restricted-token sandboxes (allow_read_all=True):
     For each sandbox metadata file in ~/.qwenpaw/sandboxes/*.json:
        1. Removes ACLs for capability SID and user SID from recorded paths
        2. Verifies ACL removal succeeded (re-checks each path)
        3. Removes Windows Firewall block rules for the sandbox user
        4. Deletes the local user account
        5. Removes the user's profile directory
        6. Deletes the metadata JSON file

  After all entries are processed:
     - Removes any remaining NTFS junctions in ~/.qwenpaw/junctions/
     - Removes the QwenpawUsers local group (if empty)
     - Removes empty state directories

This per-file approach allows the script to be interrupted and resumed
safely — only fully-cleaned entries have their JSON removed.

Safe to run multiple times (idempotent).
Requires administrator privileges.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _is_admin() -> bool:
    """Check if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def _get_state_dir() -> Path:
    """Returns the QwenPaw state directory (~/.qwenpaw)."""
    return (
        Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
        / ".qwenpaw"
    )


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


def _get_appcontainer_sid(container_name: str) -> Optional[str]:
    """Derives the SID for a container name (returns None if not found)."""
    try:
        userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
        psid = ctypes.c_void_p()
        hr = userenv.DeriveAppContainerSidFromAppContainerName(
            ctypes.c_wchar_p(container_name),
            ctypes.byref(psid),
        )
        if hr != 0:
            return None
        string_sid = ctypes.c_wchar_p()
        advapi32.ConvertSidToStringSidW(psid, ctypes.byref(string_sid))
        sid_str = string_sid.value
        ctypes.windll.kernel32.LocalFree(string_sid)
        ctypes.windll.ole32.CoTaskMemFree(psid)
        return sid_str
    except OSError:
        return None


def _run_icacls(args: List[str]) -> bool:
    """Runs icacls synchronously, returns True on success."""
    try:
        result = subprocess.run(
            ["icacls"] + args,
            capture_output=True,
            timeout=180,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_icacls_output(args: List[str]) -> Optional[str]:
    """Runs icacls and returns stdout as string, or None on failure."""
    try:
        result = subprocess.run(
            ["icacls"] + args,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")
        return result.stdout.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        return None


def _verify_acl_removed(path: str, sid: str) -> bool:
    """Verifies that a SID no longer appears in the DACL of a path.

    Runs ``icacls <path>`` and checks that the SID string does not appear
    in the output. Checks both the raw SID and common display variants.

    Returns True if the SID is confirmed absent from the path's ACL.
    """
    if not os.path.exists(path):
        return True
    output = _run_icacls_output([path])
    if output is None:
        # Cannot read ACL — treat as unverified (not confirmed removed)
        return False
    # icacls may display the SID in several forms:
    #   - Raw:  S-1-5-21-1234-5678-9012-3456
    #   - Star: *S-1-5-21-1234-5678-9012-3456
    # Check for the SID substring anywhere in the output.
    if sid in output:
        return False
    # Also check case-insensitively (some locales may uppercase)
    if sid.upper() in output.upper():
        return False
    return True


def _remove_acl_from_path(path: str, sid: str) -> None:
    """Removes all ACEs for a SID from a path (best-effort, non-recursive)."""
    if not os.path.exists(path):
        return
    _run_icacls([path, "/remove", f"*{sid}"])


def _remove_acl_recursive(path: str, sid: str) -> None:
    """Removes all ACEs for a SID from a path recursively."""
    if not os.path.exists(path):
        return
    _run_icacls([path, "/remove", f"*{sid}", "/T", "/C"])


_ACL_MAX_RETRIES = 5
_ACL_RETRY_DELAY_SECONDS = 1


def _remove_acl_with_verify(path: str, sid: str, label: str) -> bool:
    """Removes ACEs for a SID from a path and verifies removal.

    Uses a multi-strategy retry loop to ensure the ACL is truly gone:
      1. Basic ``/remove`` on the path itself.
      2. Recursive ``/remove /T /C`` to catch inherited ACEs on children.
      3. Explicit ``/remove:g`` (grant) and ``/remove:d`` (deny) variants
         which target specific ACE types that ``/remove`` alone may miss.
      4. ``/inheritance:e`` to re-enable inheritance, then remove again
         (handles cases where a broken inheritance prevents ACE removal).
      5. ``/inheritance:d`` to break inheritance (copy), then remove.
      6. Non-recursive ``/reset`` on target path only, then remove
         (last resort — resets only the target directory's DACL to
         inherited defaults, does not affect child objects).

    Each strategy is followed by a verification check. If verification
    passes at any point the function returns True immediately.

    A short delay is inserted between retries to allow the filesystem
    metadata to settle (relevant on ReFS and remote/redirected volumes).

    Returns True if the ACL was confirmed removed (or path doesn't exist).
    Returns False only after all retries are exhausted AND the SID is still
    present in the DACL output.
    """
    import time

    if not os.path.exists(path):
        return True

    # Strategy sequence — each is progressively more aggressive
    strategies = [
        # Strategy 1: simple remove
        lambda: _run_icacls([path, "/remove", f"*{sid}"]),
        # Strategy 2: recursive remove
        lambda: _run_icacls([path, "/remove", f"*{sid}", "/T", "/C"]),
        # Strategy 3: explicit grant + deny removal
        lambda: (
            _run_icacls([path, "/remove:g", f"*{sid}", "/T", "/C"]),
            _run_icacls([path, "/remove:d", f"*{sid}", "/T", "/C"]),
        ),
        # Strategy 4: re-enable inheritance then remove again
        lambda: (
            _run_icacls([path, "/inheritance:e"]),
            _run_icacls([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
        # Strategy 5: break inheritance (copy), then remove
        lambda: (
            _run_icacls([path, "/inheritance:d"]),
            _run_icacls([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
        # Strategy 6: non-recursive reset on target path only, then remove
        # (resets only the target directory's DACL to inherited defaults,
        # does NOT affect child objects — safe for workspace directories)
        lambda: (
            _run_icacls([path, "/reset"]),
            _run_icacls([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
    ]

    for attempt, strategy in enumerate(strategies, 1):
        strategy()

        # Brief delay to let filesystem metadata flush
        if attempt > 1:
            time.sleep(_ACL_RETRY_DELAY_SECONDS)

        if _verify_acl_removed(path, sid):
            if attempt > 1:
                print(f"      ACL removed on retry #{attempt} for: {path}")
            return True

    # All strategies exhausted — final report
    print(
        f"    ERROR: ACL for {label} SID ({sid}) could NOT be removed "
        f"from: {path} after {len(strategies)} attempts.",
    )
    return False


def _remove_junction(junction_path: str) -> bool:
    """Removes an NTFS junction (rmdir only removes the link, not target)."""
    try:
        if os.path.isdir(junction_path):
            os.rmdir(junction_path)
            return True
    except OSError:
        pass
    return False


def _remove_container_acl_entries(
    sid: str,
    acl_manifest: Optional[dict],
    workspace_dir: str,
    state_dir: Path,
    fallback_global_paths: List[str],
) -> None:
    """Remove ACL entries for a container SID."""
    if acl_manifest:
        # Use the precise ACL manifest recorded at creation time
        grant_paths = acl_manifest.get("grant_paths", [])
        inheritance_broken_paths = acl_manifest.get(
            "inheritance_broken_paths",
            [],
        )

        # Remove ACEs from grant paths
        for path in grant_paths:
            if path and os.path.exists(path):
                print(f"    Removing ACL from: {path}")
                _remove_acl_from_path(path, sid)

        # Recursively remove ACEs from workspace (set with (OI)(CI))
        if workspace_dir and os.path.exists(workspace_dir):
            print(
                f"    Removing ACLs from workspace (recursive): {workspace_dir}",
            )
            _remove_acl_recursive(workspace_dir, sid)

        # Remove ACEs and restore inheritance on broken paths
        for path in inheritance_broken_paths:
            if path and os.path.exists(path):
                print(f"    Removing ACL + restoring inheritance: {path}")
                _remove_acl_from_path(path, sid)
                _run_icacls([path, "/inheritance:e"])
    else:
        # Legacy metadata without manifest — use best-effort fallback
        print("    (legacy metadata, using fallback path list)")
        for path in fallback_global_paths:
            if path and os.path.exists(path):
                _remove_acl_from_path(path, sid)

        if workspace_dir and os.path.exists(workspace_dir):
            print(f"    Removing ACLs from workspace: {workspace_dir}")
            _remove_acl_recursive(workspace_dir, sid)

        junctions_dir_str = str(state_dir / "junctions")
        if os.path.exists(junctions_dir_str):
            _remove_acl_recursive(junctions_dir_str, sid)

        if workspace_dir and os.path.exists(workspace_dir):
            _run_icacls([workspace_dir, "/inheritance:e"])


def _cleanup_single_container(
    meta_file: Path,
    state_dir: Path,
    fallback_global_paths: List[str],
) -> None:
    """Clean up a single container: ACLs -> junction -> profile -> JSON file.

    Each container is fully cleaned before its metadata file is removed,
    allowing the script to be interrupted and resumed without leaving
    partially-cleaned state.
    """
    # Load metadata
    try:
        with open(meta_file, "r", encoding="utf-8") as fp:
            meta = json.load(fp)
    except (json.JSONDecodeError, OSError) as e:
        print(f"\n  WARNING: Cannot read {meta_file.name}: {e}")
        print("    Removing invalid metadata file.")
        try:
            meta_file.unlink()
        except OSError:
            pass
        return

    container_name = meta.get("container_name", "")
    sid = meta.get("sid", "")
    workspace_dir = meta.get("workspace_dir", "")
    junction_path = meta.get("junction_path", "")
    acl_manifest = meta.get("acl_manifest")

    print(f"\n  Container: {container_name}")
    print(f"    SID: {sid}")

    # Step 1: Resolve SID if missing
    if not sid:
        sid = _get_appcontainer_sid(container_name) or ""
        if sid:
            print(f"    Derived SID: {sid}")
        else:
            print("    WARNING: Cannot determine SID, skipping ACL removal.")

    # Step 2: Remove ACL entries
    if sid:
        _remove_container_acl_entries(
            sid,
            acl_manifest,
            workspace_dir,
            state_dir,
            fallback_global_paths,
        )

    # Step 3: Remove the associated junction
    if junction_path and os.path.exists(junction_path):
        print(f"    Removing junction: {junction_path}")
        if _remove_junction(junction_path):
            print("    Junction removed.")
        else:
            print("    WARNING: Failed to remove junction.")

    # Step 4: Delete the AppContainer profile
    if container_name:
        ok = _delete_appcontainer_profile(container_name)
        print(
            f"    Delete profile: {'OK' if ok else 'FAILED (may not exist)'}",
        )

    # Step 5: Delete the metadata JSON file (marks this container as done)
    try:
        meta_file.unlink()
        print(f"    Deleted metadata: {meta_file.name}")
    except OSError as e:
        print(f"    WARNING: Failed to delete {meta_file.name}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Restricted-token sandbox cleanup
# ═══════════════════════════════════════════════════════════════════════════


def _remove_firewall_rules(username: str) -> bool:
    """Removes the firewall block rules installed for a restricted sandbox user.

    Returns True if removal succeeded (or rules did not exist).
    """
    rule_name_out = f"QwenPaw_Block_{username}_Out"
    rule_name_in = f"QwenPaw_Block_{username}_In"

    ps_script = (
        f"Remove-NetFirewallRule -DisplayName '{rule_name_out}' "
        f"-ErrorAction SilentlyContinue; "
        f"Remove-NetFirewallRule -DisplayName '{rule_name_in}' "
        f"-ErrorAction SilentlyContinue"
    )

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _delete_local_user(username: str) -> bool:
    """Deletes a local Windows user account via 'net user /delete'."""
    try:
        result = subprocess.run(
            ["net", "user", username, "/delete"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _delete_local_group(group_name: str) -> bool:
    """Deletes a local Windows group via 'net localgroup /delete'."""
    try:
        result = subprocess.run(
            ["net", "localgroup", group_name, "/delete"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _remove_user_profile_dir(username: str) -> bool:
    """Removes the user profile directory (C:\\Users\\<username>).

    Windows profile directories created via CreateProfile contain subdirectories
    owned by TrustedInstaller (e.g. AppData\\Local\\Microsoft\\Windows\\WinX)
    which cannot be deleted even by Administrators without first taking ownership.

    This function performs:
      1. takeown /F ... /R /A  — transfers ownership to Administrators group
      2. icacls ... /grant Administrators:(OI)(CI)F /T /C  — grants full control
      3. shutil.rmtree with an onerror handler for residual read-only files
    """
    sys_drive = os.environ.get("SystemDrive", "C:")
    profile_dir = os.path.join(sys_drive + os.sep, "Users", username)
    if not os.path.exists(profile_dir):
        return True

    # Step 1: Take ownership of the entire tree (handles TrustedInstaller-owned dirs)
    try:
        subprocess.run(
            ["takeown", "/F", profile_dir, "/R", "/A", "/D", "Y"],
            capture_output=True,
            timeout=300,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Step 2: Grant Administrators full control recursively
    try:
        subprocess.run(
            [
                "icacls",
                profile_dir,
                "/grant",
                "Administrators:(OI)(CI)F",
                "/T",
                "/C",
            ],
            capture_output=True,
            timeout=300,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Step 3: Remove the directory tree with a fallback error handler
    def _on_rm_error(func, path, _exc_info):  # type: ignore[no-untyped-def]
        """Handle removal errors by clearing read-only attr."""
        import stat

        try:
            os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
            func(path)
        except OSError:
            pass

    try:
        # pylint: disable=deprecated-argument
        shutil.rmtree(profile_dir, onerror=_on_rm_error)
    except OSError:
        pass

    # Verify removal
    if os.path.exists(profile_dir):
        print(
            f"    WARNING: Profile dir {profile_dir} could not be fully removed. "
            f"Run 'rmdir /S /Q \"{profile_dir}\"' manually from an elevated prompt.",
        )
        return False
    return True


def _cleanup_single_restricted_sandbox(  # pylint: disable=too-many-branches,too-many-statements
    meta_file: Path,
) -> None:
    """Clean up a single restricted-token sandbox.

    Steps:
        1. Remove ACLs for capability SID and user SID (with verification)
        2. Remove firewall block rules
        3. Delete the local user account
        4. Remove the user profile directory
        5. Delete the metadata JSON file

    Each sandbox is fully cleaned before its metadata file is removed,
    allowing the script to be interrupted and resumed safely.
    """
    # Load metadata
    try:
        with open(meta_file, "r", encoding="utf-8") as fp:
            meta = json.load(fp)
    except (json.JSONDecodeError, OSError) as e:
        print(f"\n  WARNING: Cannot read {meta_file.name}: {e}")
        print("    Removing invalid metadata file.")
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

    print(f"\n  Restricted Sandbox: {sandbox_id}")
    print(f"    Username: {username}")
    print(f"    User SID: {user_sid}")
    print(f"    Cap SID:  {cap_sid}")

    # Step 1: Remove ACL entries with verification and retry
    verify_failures = 0
    verify_successes = 0
    total_processed = 0
    if acl_entries:
        print(f"    Removing {len(acl_entries)} ACL entries...")
        for entry in acl_entries:
            entry_path = entry.get("path", "")
            sid_type = entry.get("sid_type", "")

            if not entry_path:
                continue

            # Determine which SID was used for this ACE
            if sid_type == "cap":
                sid = cap_sid
                sid_label = "capability"
            elif sid_type == "user":
                sid = user_sid
                sid_label = "user"
            else:
                # Unknown type — try both
                sid = cap_sid or user_sid
                sid_label = "unknown"

            if not sid:
                print(
                    f"    WARNING: No SID available for {sid_label} entry on {entry_path}",
                )
                continue

            if not os.path.exists(entry_path):
                continue

            total_processed += 1
            print(f"    Removing {sid_label} ACL from: {entry_path}")
            ok = _remove_acl_with_verify(entry_path, sid, sid_label)
            if ok:
                verify_successes += 1
            else:
                verify_failures += 1
    else:
        # No acl_entries recorded — try removing both SIDs from common paths
        print("    (no ACL entries recorded, skipping ACL removal)")

    # Also clean up profile directory ACLs if they exist
    if username:
        sys_drive = os.environ.get("SystemDrive", "C:")
        profile_dir = os.path.join(sys_drive + os.sep, "Users", username)
        if os.path.exists(profile_dir):
            if cap_sid:
                print(
                    f"    Removing capability ACL from profile: {profile_dir}",
                )
                ok = _remove_acl_with_verify(
                    profile_dir,
                    cap_sid,
                    "capability",
                )
                total_processed += 1
                if ok:
                    verify_successes += 1
                else:
                    verify_failures += 1
            if user_sid:
                print(f"    Removing user ACL from profile: {profile_dir}")
                ok = _remove_acl_with_verify(profile_dir, user_sid, "user")
                total_processed += 1
                if ok:
                    verify_successes += 1
                else:
                    verify_failures += 1

    if total_processed > 0:
        print(
            f"    ACL cleanup summary: {verify_successes}/{total_processed} "
            f"confirmed removed"
            + (f", {verify_failures} FAILED" if verify_failures > 0 else ""),
        )
    if verify_failures > 0:
        print(
            f"    ERROR: {verify_failures} ACL(s) could NOT be removed after "
            f"all retries. Manual intervention may be required.",
        )
        print(
            "    Hint: Run 'icacls <path> /remove *<SID> /T /C' manually, "
            "or take ownership with 'takeown /F <path> /R' first.",
        )

    # Step 2: Remove firewall rules
    if network_blocked and username:
        print(f"    Removing firewall rules for: {username}")
        ok = _remove_firewall_rules(username)
        print(
            f"    Firewall rules: {'removed' if ok else 'removal failed (may not exist)'}",
        )

    # Step 3: Delete the local user account
    if username:
        print(f"    Deleting user account: {username}")
        ok = _delete_local_user(username)
        print(
            f"    User account: {'deleted' if ok else 'deletion failed (may not exist)'}",
        )

    # Step 4: Remove user profile directory
    if username:
        sys_drive = os.environ.get("SystemDrive", "C:")
        profile_dir = os.path.join(sys_drive + os.sep, "Users", username)
        if os.path.exists(profile_dir):
            print(f"    Removing profile directory: {profile_dir}")
            ok = _remove_user_profile_dir(username)
            print(
                f"    Profile directory: {'removed' if ok else 'removal failed'}",
            )

    # Step 5: Delete the metadata JSON file (marks this sandbox as done)
    try:
        meta_file.unlink()
        print(f"    Deleted metadata: {meta_file.name}")
    except OSError as e:
        print(f"    WARNING: Failed to delete {meta_file.name}: {e}")


def _remove_python_dir_acl_marker() -> None:
    """Removes the .qwenpaw_acl_granted marker from the Python install directory.

    This marker is written by _ensure_python_dir_group_acl() after granting
    RX to QwenpawUsers on the Python dir. When cleanup removes the group
    (and its ACL is gone), the marker must also be removed so that the next
    sandbox creation will re-grant the ACL properly.
    """
    python_dir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.basename(python_dir).lower() == "scripts":
        python_dir = os.path.dirname(python_dir)

    marker = os.path.join(python_dir, ".qwenpaw_acl_granted")
    if os.path.exists(marker):
        try:
            os.remove(marker)
            print(f"    Removed ACL marker: {marker}")
        except OSError as e:
            print(f"    WARNING: Failed to remove ACL marker {marker}: {e}")
    else:
        print("    ACL marker not present (already clean).")


def _cleanup_sandbox_group() -> None:
    """Removes the QwenpawUsers local group if it exists."""
    print("\n  Removing QwenpawUsers group...")
    ok = _delete_local_group("QwenpawUsers")
    if ok:
        print("    Group deleted.")
    else:
        print("    Group deletion failed (may not exist or not empty).")

    # Remove the .qwenpaw_acl_granted marker from Python directory.
    # Without this, the next sandbox creation would see the stale marker
    # and skip re-granting the ACL to the (re-created) QwenpawUsers group.
    _remove_python_dir_acl_marker()


# ═══════════════════════════════════════════════════════════════════════════
# Common cleanup helpers
# ═══════════════════════════════════════════════════════════════════════════


def _cleanup_remaining_junctions(state_dir: Path) -> None:
    """Remove any remaining NTFS junctions not tied to a metadata file."""
    junctions_dir = state_dir / "junctions"
    print(f"\n[3] Removing remaining NTFS junctions from: {junctions_dir}")
    if junctions_dir.is_dir():
        count = 0
        for entry in junctions_dir.iterdir():
            if entry.is_dir():
                if _remove_junction(str(entry)):
                    count += 1
                else:
                    print(f"    WARNING: Failed to remove junction: {entry}")
        print(f"    Removed {count} junction(s).")
    else:
        print("    No junctions directory found.")


def _cleanup_state_dirs(state_dir: Path) -> None:
    """Remove state directories (containers/, sandboxes/, junctions/) and clean up."""
    print("\n[4] Removing state directories...")
    junctions_dir = state_dir / "junctions"
    containers_dir = state_dir / "containers"
    sandboxes_dir = state_dir / "sandboxes"
    for d in [containers_dir, sandboxes_dir, junctions_dir]:
        if d.is_dir():
            try:
                shutil.rmtree(str(d))
                print(f"    Removed: {d}")
            except OSError as e:
                print(f"    WARNING: Failed to remove {d}: {e}")
        elif d.exists():
            # Handle case where path exists but isn't a directory
            try:
                d.unlink()
                print(f"    Removed file: {d}")
            except OSError as e:
                print(f"    WARNING: Failed to remove {d}: {e}")

    # Remove any remaining files in .qwenpaw (stray files, logs, etc.)
    if state_dir.is_dir():
        remaining = list(state_dir.iterdir())
        if not remaining:
            try:
                state_dir.rmdir()
                print(f"    Removed empty state dir: {state_dir}")
            except OSError:
                pass
        else:
            print(
                f"    State dir not empty, remaining items: "
                f"{[e.name for e in remaining]}",
            )


def main() -> None:  # pylint: disable=too-many-statements
    if sys.platform != "win32":
        print("ERROR: This script must run on Windows.")
        sys.exit(1)

    if not _is_admin():
        print("ERROR: This script requires administrator privileges.")
        print(
            "Please run as administrator (right-click -> Run as administrator).",
        )
        sys.exit(1)

    state_dir = _get_state_dir()
    containers_dir = state_dir / "containers"
    sandboxes_dir = state_dir / "sandboxes"

    # Count what we're about to clean
    appcontainer_count = 0
    restricted_count = 0
    if containers_dir.is_dir():
        appcontainer_count = len(list(containers_dir.glob("*.json")))
    if sandboxes_dir.is_dir():
        restricted_count = len(list(sandboxes_dir.glob("*.json")))

    print("=" * 60)
    print("WARNING: This will clean up ALL QwenPaw sandboxes,")
    print("including any that are currently RUNNING.")
    print()
    print(f"  AppContainer sandboxes found:       {appcontainer_count}")
    print(f"  Restricted-token sandboxes found:   {restricted_count}")
    print()
    print("The following actions will be performed:")
    print("  - Remove filesystem ACLs set by sandboxes")
    print("  - Delete AppContainer profiles")
    print("  - Delete local sandbox user accounts (qwenpaw_*)")
    print("  - Remove firewall block rules")
    print("  - Remove user profile directories")
    print("  - Delete sandbox metadata files")
    print()
    print("Please make sure no sandbox is currently in use before proceeding.")
    print("=" * 60)
    print()
    choice = input("Do you want to continue? (Y/N): ").strip().upper()
    if choice != "Y":
        print("Aborted by user.")
        sys.exit(0)
    print()

    print("=" * 60)
    print("QwenPaw Sandbox Cleanup")
    print("=" * 60)
    print(f"  State directory: {state_dir}")
    print()

    # Fallback paths for legacy metadata without acl_manifest
    sys_drive = os.environ.get("SystemDrive", "C:")
    users_dir = sys_drive + "\\Users"
    user_profile = os.environ.get("USERPROFILE", "")
    fallback_global_paths = [
        sys_drive + "\\",
        users_dir,
        user_profile,
        os.path.dirname(sys.executable),
    ]

    # ── Step 1: Process AppContainer sandboxes ──
    if containers_dir.is_dir():
        json_files = sorted(containers_dir.glob("*.json"))
        print(f"[1] Found {len(json_files)} AppContainer metadata file(s).")

        for meta_file in json_files:
            _cleanup_single_container(
                meta_file,
                state_dir,
                fallback_global_paths,
            )
    else:
        print("[1] No AppContainer metadata directory found.")

    # ── Step 2: Process restricted-token sandboxes ──
    if sandboxes_dir.is_dir():
        json_files = sorted(sandboxes_dir.glob("*.json"))
        print(
            f"\n[2] Found {len(json_files)} restricted-token sandbox metadata file(s).",
        )

        for meta_file in json_files:
            _cleanup_single_restricted_sandbox(meta_file)

        # Remove the shared local group after all users are deleted
        _cleanup_sandbox_group()
    else:
        print("\n[2] No restricted-token sandbox metadata directory found.")

    # ── Step 3: Remove any remaining junctions ──
    _cleanup_remaining_junctions(state_dir)

    # ── Step 4: Remove state directories ──
    _cleanup_state_dirs(state_dir)

    print("\n" + "=" * 60)
    print("Cleanup complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
