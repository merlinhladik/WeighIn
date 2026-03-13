import os
import shlex
import shutil
import subprocess
import sys


def _binary_name(name):
    if sys.platform.startswith("win"):
        return f"{name}.exe"
    return name


def _binary_path(base, name):
    return os.path.join(base, _binary_name(name))


def _elevated_command(binary_path):
    if sys.platform == "darwin":
        quoted_path = shlex.quote(binary_path)
        script = f"do shell script {quoted_path!r} with administrator privileges"
        return ["osascript", "-e", script]

    if sys.platform.startswith("linux"):
        if shutil.which("pkexec"):
            return ["pkexec", binary_path]
        return ["sudo", binary_path]

    return [binary_path]


def _start_process(base, name, requires_root=False):
    binary_path = _binary_path(base, name)
    command = _elevated_command(binary_path) if requires_root else [binary_path]
    return subprocess.Popen(command, cwd=base)


def _stop_process(process):
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main():
    base = os.path.dirname(sys.executable)

    gui = _start_process(base, "gui", requires_root=not sys.platform.startswith("win"))
    weight = _start_process(base, "weight")
    scanner = _start_process(
        base, "real_scanner", requires_root=not sys.platform.startswith("win")
    )

    try:
        gui.wait()
    finally:
        for process in (weight, scanner):
            _stop_process(process)


if __name__ == "__main__":
    main()
