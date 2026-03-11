import subprocess
import os
import sys


def main():
    base = os.path.dirname(sys.executable)

    if sys.platform.startswith("win"):
        gui_name = "gui.exe"
        weight_name = "weight.exe"
        scanner_name = "real_scanner.exe"
    else:
        gui_name = "gui"
        weight_name = "weight"
        scanner_name = "real_scanner"

    gui = subprocess.Popen([os.path.join(base, gui_name)])
    weight = subprocess.Popen([os.path.join(base, weight_name)])
    scanner = subprocess.Popen([os.path.join(base, scanner_name)])

    gui.wait()

    weight.kill()
    scanner.kill()


if __name__ == "__main__":
    main()