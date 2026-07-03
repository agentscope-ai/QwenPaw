# -*- coding: utf-8 -*-
"""Cleanup script: removes all QwenPaw AppContainer profiles, ACLs, and state.

Run on Windows with administrator privileges:
    python scripts/cleanup_windows_sandbox.py

This script performs the following cleanup steps:
    For each container metadata file in ~/.qwenpaw/containers/*.json:
        1. Removes ACLs (icacls /remove) from known paths
        2. Removes the associated NTFS junction
        3. Deletes the AppContainer profile via userenv.dll
        4. Deletes the metadata JSON file

    After all containers are processed:
        5. Removes any remaining NTFS junctions in ~/.qwenpaw/junctions/
        6. Removes empty state directories

This per-file approach allows the script to be interrupted and resumed
safely — only fully-cleaned containers have their JSON removed.

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
    """Clean up a single container: ACLs → junction → profile → JSON file.

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


def _cleanup_remaining_junctions(state_dir: Path) -> None:
    """Remove any remaining NTFS junctions not tied to a metadata file."""
    junctions_dir = state_dir / "junctions"
    print(f"\n[2] Removing remaining NTFS junctions from: {junctions_dir}")
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
    """Remove state directories (containers/, junctions/) and clean up."""
    print("\n[3] Removing state directories...")
    junctions_dir = state_dir / "junctions"
    containers_dir = state_dir / "containers"
    for d in [containers_dir, junctions_dir]:
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


def main() -> None:
    if sys.platform != "win32":
        print("ERROR: This script must run on Windows.")
        sys.exit(1)

    if not _is_admin():
        print("ERROR: This script requires administrator privileges.")
        print(
            "Please run as administrator (right-click → Run as administrator).",
        )
        sys.exit(1)

    print("=" * 60)
    print("WARNING: This will clean up ALL QwenPaw AppContainer sandboxes,")
    print("including any that are currently RUNNING.")
    print("Please make sure no sandbox is currently in use before proceeding.")
    print("=" * 60)
    print()
    choice = input("Do you want to continue? (Y/N): ").strip().upper()
    if choice != "Y":
        print("Aborted by user.")
        sys.exit(0)
    print()

    state_dir = _get_state_dir()
    print("=" * 60)
    print("QwenPaw AppContainer Cleanup")
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

    # Step 1: Process each container metadata file individually
    containers_dir = state_dir / "containers"
    if containers_dir.is_dir():
        json_files = sorted(containers_dir.glob("*.json"))
        print(f"[1] Found {len(json_files)} container metadata file(s).")

        for meta_file in json_files:
            _cleanup_single_container(
                meta_file,
                state_dir,
                fallback_global_paths,
            )
    else:
        print("[1] No container metadata directory found.")

    # Step 2: Remove any remaining junctions
    _cleanup_remaining_junctions(state_dir)

    # Step 3: Remove state directories
    _cleanup_state_dirs(state_dir)

    print("\n" + "=" * 60)
    print("Cleanup complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
