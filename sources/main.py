import os
import shlex
import shutil
import signal
import subprocess
import sys
import time


SOFT_STOP_TIMEOUT_S = 5.0
HARD_STOP_TIMEOUT_S = 2.0
ASKPASS_CANDIDATES = (
    "ssh-askpass",
    "ksshaskpass",
    "ksshaskpass5",
    "lxqt-sudo",
)


def _binary_name(name):
    if sys.platform.startswith("win"):
        return f"{name}.exe"
    return name


def _binary_path(base, name):
    return os.path.join(base, _binary_name(name))


def _linux_display_env():
    env = {}
    for key in (
        "DISPLAY",
        "XAUTHORITY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
    ):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _resolve_askpass():
    explicit = os.environ.get("SUDO_ASKPASS")
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return explicit

    for program in ASKPASS_CANDIDATES:
        found = shutil.which(program)
        if found:
            return found
    return None


def _elevated_command(binary_path, askpass_path=None):
    if sys.platform == "darwin":
        quoted_path = shlex.quote(binary_path)
        script = f"do shell script {quoted_path!r} with administrator privileges"
        return ["osascript", "-e", script]

    if sys.platform.startswith("linux"):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return [binary_path]
        if shutil.which("sudo"):
            # Keep DISPLAY/XAUTHORITY and session vars for GUI apps.
            if askpass_path:
                return ["sudo", "-A", "-E", binary_path]
            return ["sudo", "-E", binary_path]
        if shutil.which("pkexec"):
            return ["pkexec", binary_path]
        return [binary_path]

    return [binary_path]


def _start_process(base, name, requires_root=False):
    binary_path = _binary_path(base, name)
    askpass_path = _resolve_askpass() if requires_root and sys.platform.startswith("linux") else None
    command = _elevated_command(binary_path, askpass_path=askpass_path) if requires_root else [binary_path]

    env = os.environ.copy()
    if sys.platform.startswith("linux"):
        env.update(_linux_display_env())
        if askpass_path:
            env["SUDO_ASKPASS"] = askpass_path

    popen_kwargs = {"cwd": base, "env": env}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["preexec_fn"] = os.setsid
    return subprocess.Popen(command, **popen_kwargs)


def _wait_for_exit(process, timeout_s):
    try:
        process.wait(timeout=timeout_s)
        return True
    except subprocess.TimeoutExpired:
        return False


def _stop_process(process):
    if process is None:
        return

    try:
        if process.poll() is not None:
            return

        pid = process.pid

        # --- Linux / macOS ---
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                process.terminate()

            if not _wait_for_exit(process, SOFT_STOP_TIMEOUT_S):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except Exception:
                    process.kill()
                _wait_for_exit(process, HARD_STOP_TIMEOUT_S)

        # --- Windows ---
        else:
            subprocess.run(
                ["taskkill", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if not _wait_for_exit(process, SOFT_STOP_TIMEOUT_S):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                _wait_for_exit(process, HARD_STOP_TIMEOUT_S)

    except Exception as e:
        print(f"Failed to stop process: {e}")

        
def main():
    base = os.path.dirname(sys.executable)

    gui = _start_process(base, "gui", requires_root=False)
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
