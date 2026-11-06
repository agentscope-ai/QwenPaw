# Upstream attribution

This app is a narrow PawApp v2.2 adaptation of the directory-listing behavior
from [`chcsyf/qwenpaw-file-browser`](https://github.com/chcsyf/qwenpaw-file-browser),
version 0.2.3, commit `8870a8cc1344c758cabb9ba46e36d9a7e92b625e`.
The upstream project is licensed under Apache-2.0.

The Marketplace archive was not copied or executed because the archive fetched
on 2026-09-16 had SHA-256
`4a35a29051be306982e0d07e16ef919301676577ccd37850c74fddeab8500cba`, which did
not match the reviewed design pin
`6275013f0ce73279380f52d5b008cfbba1904c266778054f890e920b072b4377`.

This adaptation keeps only a bounded, non-recursive, read-only directory
listing. It excludes file writes, terminal access, AI endpoints, and
process-global mode state. Host task grants remain separate from the saved
default directory.
