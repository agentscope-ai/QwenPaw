/*
 * Copyright 2026 Cisco Systems, Inc. and its affiliates
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/*
 * Detects embedded executable content in binary files within skill packages.
 * Catches ELF binaries, PE executables, Mach-O binaries, and shebang scripts
 * that may indicate supply chain compromise or hidden payloads.
 */

rule embedded_elf_binary
{
    meta:
        author = "Cisco Security & Ping"
        description = "Detects ELF executable headers embedded in skill package files"
        classification = "harmful"
        threat_type = "EMBEDDED BINARY"

    strings:
        $elf_magic = { 7F 45 4C 46 }  // ELF magic bytes

    condition:
        $elf_magic
}

rule embedded_pe_executable
{
    meta:
        author = "Cisco Security & Ping"
        description = "Detects PE (Windows) executable headers embedded in skill package files"
        classification = "harmful"
        threat_type = "EMBEDDED BINARY"

    strings:
        $mz_header = { 4D 5A }  // MZ header
        $pe_sig = "PE\x00\x00"

    condition:
        $mz_header at 0 and $pe_sig
}

rule embedded_macho_binary
{
    meta:
        author = "Cisco Security"
        description = "Detects Mach-O (macOS) executable headers embedded in skill package files"
        classification = "harmful"
        threat_type = "EMBEDDED BINARY"

    strings:
        $macho_32 = { CE FA ED FE }  // 32-bit Mach-O
        $macho_64 = { CF FA ED FE }  // 64-bit Mach-O
        $macho_fat = { CA FE BA BE }  // Universal/fat binary

    condition:
        ($macho_32 at 0) or ($macho_64 at 0) or ($macho_fat at 0)
}

rule embedded_shebang_in_binary
{
    meta:
        author = "Cisco Security"
        description = "Detects shebang script headers embedded within binary content"
        classification = "suspicious"
        threat_type = "EMBEDDED BINARY"

    strings:
        $shebang_bash = "#!/bin/bash"
        $shebang_sh = "#!/bin/sh"
        $shebang_python = "#!/usr/bin/env python"
        $shebang_python3 = "#!/usr/bin/python"
        $shebang_perl = "#!/usr/bin/perl"
        $shebang_ruby = "#!/usr/bin/ruby"
        $shebang_node = "#!/usr/bin/env node"

    condition:
        // Only flag when shebang is deeply embedded (offset > 64), not just after
        // a small header. The application layer also restricts this rule to binary
        // files only; text files with shebangs in code blocks are not flagged.
        for any of ($shebang_*) : (@ > 64)
}
