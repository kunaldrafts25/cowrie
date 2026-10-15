# SPDX-FileCopyrightText: 2019 NunoNovais <nuno@novais.me>
# SPDX-FileCopyrightText: 2018 Free Software Foundation, Inc.\n")
# SPDX-FileCopyrightText: 2019 Nuno Novais <nuno@noais.me>
# SPDX-FileCopyrightText: 2020-2025 Michel Oosterhof <michel@oosterhof.net>
#
# SPDX-License-Identifier: BSD-3-Clause

"""
This module contains the wc commnad
"""

from __future__ import annotations

import getopt

from cowrie.shell.command import HoneyPotCommand
from cowrie.shell.fs import FileNotFound

commands = {}


class Command_wc(HoneyPotCommand):
    """
    wc command
    """

    consumes_stdin = True

    def version(self) -> None:
        self.writeBytes(b"wc (GNU coreutils) 8.30\n")
        self.writeBytes(b"Copyright (C) 2018 Free Software Foundation, Inc.\n")
        self.writeBytes(
            b"License GPLv3+: GNU GPL version 3 or later <https://gnu.org/licenses/gpl.html>.\n"
        )
        self.writeBytes(
            b"This is free software: you are free to change and redistribute it.\n"
        )
        self.writeBytes(b"There is NO WARRANTY, to the extent permitted by law.\n")
        self.writeBytes(b"\n")
        self.writeBytes(b"Written by Paul Rubin and David MacKenzie.\n")

    def help(self) -> None:
        self.writeBytes(b"Usage: wc [OPTION]... [FILE]...\n")
        self.writeBytes(
            b"Print newline, word, and byte counts for each FILE, and a total line if\n"
        )
        self.writeBytes(
            b"more than one FILE is specified.  A word is a non-zero-length sequence of\n"
        )
        self.writeBytes(b"characters delimited by white space.\n")
        self.writeBytes(b"\n")
        self.writeBytes(b"With no FILE, or when FILE is -, read standard input.\n")
        self.writeBytes(b"\n")
        self.writeBytes(
            b"The options below may be used to select which counts are printed, always in\n"
        )
        self.writeBytes(
            b"the following order: newline, word, character, byte, maximum line length.\n"
        )
        self.writeBytes(b"\t-c\tprint the byte counts\n")
        self.writeBytes(b"\t-m\tprint the character counts\n")
        self.writeBytes(b"\t-l\tprint the newline counts\n")
        self.writeBytes(b"\t-w\tprint the word counts\n")
        self.writeBytes(b"\t-h\tdisplay this help and exit\n")
        self.writeBytes(b"\t-v\toutput version information and exit\n")

    def wc_application(self, contents: bytes, optlist: list[tuple[str, str]]) -> None:
        selected = {opt for opt, _ in optlist} or {"-l", "-w", "-c"}
        values = {
            "-l": contents.count(b"\n"),
            "-w": len(contents.split()),
            "-m": len(contents.decode("utf-8", errors="ignore")),
            "-c": len(contents),
            "-L": max(
                (len(line.expandtabs(8)) for line in contents.splitlines()), default=0
            ),
        }
        self.write(
            " ".join(
                str(values[opt])
                for opt in ("-l", "-w", "-m", "-c", "-L")
                if opt in selected
            )
            + "\n"
        )

    def start(self) -> None:
        self._stdin = bytearray()
        try:
            self.optlist, args = getopt.getopt(self.args, "cmlLwhv")
        except getopt.GetoptError as err:
            self.errorWrite(f"wc: invalid option -- {err.opt}\n")
            self.exit(1)
            return
        for opt, _ in self.optlist:
            if opt == "-v":
                self.version()
                self.exit()
                return
            if opt == "-h":
                self.help()
                self.exit()
                return

        if not args:
            if self.input_data is None:
                return
            self.wc_application(self.input_data, self.optlist)
        else:
            for arg in args:
                if arg == "-":
                    self.wc_application(self.input_data or b"", self.optlist)
                    continue
                path = self.fs.resolve_path(arg, self.cwd)
                if self.fs.isdir(path):
                    self.errorWrite(f"wc: {arg}: Is a directory\n")
                    self.exit_code = 1
                    continue
                try:
                    self.wc_application(self.fs.file_contents(path), self.optlist)
                except FileNotFound:
                    self.errorWrite(f"wc: {arg}: No such file or directory\n")
                    self.exit_code = 1
        self.exit()

    def lineReceived(self, line: str) -> None:
        self.protocol.events.dispatch(
            "cowrie.command.input",
            "INPUT (%(realm)s): %(input)s",
            realm="wc",
            input=line,
        )
        if not hasattr(self, "_stdin"):
            self._stdin = bytearray()
        self._stdin.extend(line.encode("utf-8"))
        if not line.endswith("\n"):
            self._stdin.extend(b"\n")

    def eofReceived(self) -> None:
        self.wc_application(bytes(self._stdin), self.optlist)
        self.exit()


commands["/usr/bin/wc"] = Command_wc
commands["/bin/wc"] = Command_wc
commands["wc"] = Command_wc
