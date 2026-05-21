# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import io

from qwenpaw.tauri import logging as tauri_logging


def test_tee_stream_writes_text_to_both_streams():
    primary = io.StringIO()
    secondary = io.StringIO()
    stream = tauri_logging._TeeStream(primary, secondary)

    assert stream.write("hello") == 5
    stream.writelines([" ", "world"])

    assert primary.getvalue() == "hello world"
    assert secondary.getvalue() == "hello world"
    assert stream.writable()
    assert not stream.readable()
    assert not stream.seekable()
