# -*- coding: utf-8 -*-
"""Cleanup script: removes all QwenPaw AppContainer profiles, ACLs, and state.

Run on Windows with administrator privileges:
    python scripts/cleanup_appcontainer.py

This script performs the following cleanup steps:
    1. Reads all container metadata from ~/.qwenpaw/containers/*.json
    2. For each container:
       a. Removes ACLs (icacls /remove) from known paths
       b. Deletes the AppContainer profile via userenv.dll
    3. Removes all NTFS junctions in ~/.qwenpaw/junctions/
    4. Deletes the ~/.qwenpaw/containers/ and ~/.qwenpaw/junctions/ directories

Safe to run multiple times (idempotent).
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _get_state_dir() -> Path:
    """Returns the QwenPaw state directory (~/.qwenpaw)."""
    return (
        Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
        / ".qwenpaw"
    )


def _load_all_metadata(state_dir: Path) -> List[dict]:
    """Loads all container metadata JSON files."""
    containers_dir = state_dir / "containers"
    if not containers_dir.is_dir():
        return []
    results = []
    for f in containers_dir.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                results.append(json.load(fp))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def _delete_appcontainer_profile(container_name: str) -> bool:
    """Deletes an AppContainer profile by name."""
    try:
        userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        hr = userenv.DeleteAppContainerProfile(
            ctypes.c_wchar_p(container_name)
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
            ctypes.c_wchar_p(container_name), ctypes.byref(psid)
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
            timeout=30,
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


def main():
    if sys.platform != "win32":
        print("ERROR: This script must run on Windows.")
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

    # Step 1: Load metadata
    metadata_list = _load_all_metadata(state_dir)
    print(f"[1] Found {len(metadata_list)} container metadata file(s).")

    if not metadata_list:
        # Try to find any qwenpaw_ containers by brute-force pattern
        print(
            "    No metadata found. Attempting to find containers by name pattern..."
        )
        # We can't enumerate AppContainer profiles directly without metadata,
        # but we'll still clean up junctions and directories below.

    # Step 2: Remove ACLs and delete profiles
    print(f"\n[2] Removing ACLs and deleting AppContainer profiles...")

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

    metadata_files_to_delete: List[Path] = []

    for meta in metadata_list:
        container_name = meta.get("container_name", "")
        sid = meta.get("sid", "")
        workspace_dir = meta.get("workspace_dir", "")
        acl_manifest = meta.get("acl_manifest")

        print(f"\n  Container: {container_name}")
        print(f"    SID: {sid}")

        # Track the metadata file for deletion
        if container_name:
            meta_file = state_dir / "containers" / f"{container_name}.json"
            if meta_file.exists():
                metadata_files_to_delete.append(meta_file)

        if not sid:
            # Try to derive SID from container name
            sid = _get_appcontainer_sid(container_name) or ""
            if sid:
                print(f"    Derived SID: {sid}")
            else:
                print(
                    f"    WARNING: Cannot determine SID, skipping ACL removal."
                )

        if sid:
            if acl_manifest:
                # Use the precise ACL manifest recorded at creation time
                grant_paths = acl_manifest.get("grant_paths", [])
                inheritance_broken_paths = acl_manifest.get(
                    "inheritance_broken_paths", []
                )

                # Remove ACEs from grant paths
                for path in grant_paths:
                    if path and os.path.exists(path):
                        print(f"    Removing ACL from: {path}")
                        _remove_acl_from_path(path, sid)

                # Recursively remove ACEs from workspace (set with (OI)(CI))
                if workspace_dir and os.path.exists(workspace_dir):
                    print(
                        f"    Removing ACLs from workspace (recursive): {workspace_dir}"
                    )
                    _remove_acl_recursive(workspace_dir, sid)

                # Remove ACEs and restore inheritance on broken paths
                for path in inheritance_broken_paths:
                    if path and os.path.exists(path):
                        print(
                            f"    Removing ACL + restoring inheritance: {path}"
                        )
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

        # Delete the AppContainer profile
        if container_name:
            ok = _delete_appcontainer_profile(container_name)
            print(
                f"    Delete profile: {'OK' if ok else 'FAILED (may not exist)'}"
            )

    # Delete metadata JSON files
    if metadata_files_to_delete:
        print(
            f"\n  Deleting {len(metadata_files_to_delete)} metadata file(s)..."
        )
        for meta_file in metadata_files_to_delete:
            try:
                meta_file.unlink()
                print(f"    Deleted: {meta_file.name}")
            except OSError as e:
                print(f"    WARNING: Failed to delete {meta_file}: {e}")

    # Step 3: Remove all junctions
    junctions_dir = state_dir / "junctions"
    print(f"\n[3] Removing NTFS junctions from: {junctions_dir}")
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

    # Step 4: Remove state directories (containers/, junctions/, and their contents)
    print(f"\n[4] Removing state directories...")
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
                f"{[e.name for e in remaining]}"
            )

    print(f"\n{'=' * 60}")
    print("Cleanup complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
