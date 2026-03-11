# SPDX-FileCopyrightText: 2026 TOP Team Combat Control
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
import sys
import time


def main():
    processes = []

    gui = subprocess.Popen([sys.executable, "gui.py"])
    processes.append(gui)

    weight = subprocess.Popen([sys.executable, "weight.py"])
    processes.append(weight)

    scanner = subprocess.Popen([sys.executable, "real_scanner.py"])
    processes.append(scanner)

    gui.wait()

    for p in processes[1:]:
        p.terminate()


if __name__ == "__main__":
    main()