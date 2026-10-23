"""Real filesystem authorization race; only intercept the OS open boundary."""
import os
from pathlib import Path

from imessage_native_support import import_native


def test_local_media_parent_swap_never_copies_outside_workspace(tmp_path, monkeypatch):
    import_native()
    from qwenpaw_channel_imessage.media import IMessageMedia

    workspace = tmp_path / 'workspace'
    parent = workspace / 'attachment'
    parent.mkdir(parents=True)
    original = parent / 'document.txt'
    original.write_bytes(b'authorized original inode')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / original.name).write_bytes(b'OUTSIDE WORKSPACE SECRET')
    media = IMessageMedia({'workspace_dir': str(workspace), 'media_dir': str(workspace / 'media')}, ValueError)
    media.start()
    real_open = os.open
    swapped = False

    def open_after_parent_swap(path, flags, *args, **kwargs):
        nonlocal swapped
        if (Path(path) == original or (Path(path).name == original.name and kwargs.get('dir_fd') is not None)) and not swapped:
            swapped = True
            parent.rename(workspace / 'original-parent')
            parent.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', open_after_parent_swap)
    try:
        result = media.local_file(str(original))
    except (ValueError, OSError):
        result = None
    assert swapped, 'the controlled race must reach the actual file open'
    if result is not None:
        assert Path(result).read_bytes() == b'authorized original inode'
    assert all(path.read_bytes() != b'OUTSIDE WORKSPACE SECRET' for path in media.directory.iterdir() if path.is_file())


def test_local_media_legitimate_file_url_and_authorized_symlink(tmp_path):
    _, error, Media = import_native()
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    original = workspace / 'document.txt'
    original.write_bytes(b'authorized bytes')
    link = workspace / 'alias.txt'
    link.symlink_to(original)
    media = Media({'workspace_dir':str(workspace),'media_dir':str(workspace/'media')},error)
    media.start()
    for value in (str(original),original.as_uri(),str(link)):
        copied = Path(media.local_file(value))
        assert copied.parent == media.directory
        assert copied.read_bytes() == b'authorized bytes'
    assert media.local_file(str(workspace/'missing.txt')) is None


def test_local_media_outside_parent_symlink_remains_unauthorized(tmp_path):
    import pytest
    _, error, Media = import_native()
    workspace=tmp_path/'workspace';workspace.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    (outside/'secret.txt').write_bytes(b'OUTSIDE WORKSPACE SECRET')
    (workspace/'escape').symlink_to(outside,target_is_directory=True)
    media=Media({'workspace_dir':str(workspace),'media_dir':str(workspace/'media')},error)
    media.start()
    with pytest.raises(error,match='MEDIA_PATH_UNAUTHORIZED'):
        media.local_file(str(workspace/'escape'/'secret.txt'))
    assert list(media.directory.iterdir()) == []
