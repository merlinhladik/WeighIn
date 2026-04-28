import os
import shlex
import shutil
import signal
import subprocess
import sys
import time


SOFT_STOP_TIMEOUT_S = 5.0
HARD_STOP_TIMEOUT_S = 2.0


# ---------------------------------------------------------------------------
# macOS: posix_spawn mit responsibility_spawnattrs_setdisclaim
# ---------------------------------------------------------------------------
# Hintergrund: Wenn das .app-Bundle Kamera-/Mikrofon-/Accessibility-Berechtigung
# hat, vererbt sich die TCC-Identitaet bei subprocess.Popen NICHT automatisch
# auf Subprozesse - macOS sieht jede Mach-O-Binary als eigene Identitaet, was
# dazu fuehrt, dass cv2.VideoCapture zwar isOpened()=True liefert, aber nur
# schwarze Frames vom AVFoundation-Layer kommen (silent denial).
# Fix: posix_spawn mit responsibility_spawnattrs_setdisclaim(attr, 1), wodurch
# der Subprocess explizit auf eigene TCC-Identitaet verzichtet und die des
# Parents (des .app-Bundles) erbt.

if sys.platform == "darwin":
    import ctypes  # noqa: E402

    _libc = ctypes.CDLL(None, use_errno=True)

    _libc.posix_spawnattr_init.argtypes = [ctypes.c_void_p]
    _libc.posix_spawnattr_init.restype = ctypes.c_int
    _libc.posix_spawnattr_destroy.argtypes = [ctypes.c_void_p]
    _libc.posix_spawnattr_destroy.restype = ctypes.c_int
    _libc.posix_spawnattr_setflags.argtypes = [ctypes.c_void_p, ctypes.c_short]
    _libc.posix_spawnattr_setflags.restype = ctypes.c_int
    _libc.responsibility_spawnattrs_setdisclaim.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _libc.responsibility_spawnattrs_setdisclaim.restype = ctypes.c_int
    _libc.posix_spawn.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_char_p),
        ctypes.POINTER(ctypes.c_char_p),
    ]
    _libc.posix_spawn.restype = ctypes.c_int

    _POSIX_SPAWN_SETSID = 0x0400  # macOS: detach process from parent's session


    class _DisclaimedPopen:
        """Minimaler subprocess.Popen-Ersatz: pid, poll, wait, terminate, kill."""

        def __init__(self, pid, args):
            self.pid = pid
            self.args = args
            self.returncode = None

        def _reap(self, options):
            try:
                wpid, status = os.waitpid(self.pid, options)
            except ChildProcessError:
                self.returncode = -1
                return True
            if wpid == 0:
                return False
            if os.WIFEXITED(status):
                self.returncode = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                self.returncode = -os.WTERMSIG(status)
            else:
                self.returncode = -1
            return True

        def poll(self):
            if self.returncode is None:
                self._reap(os.WNOHANG)
            return self.returncode

        def wait(self, timeout=None):
            if self.returncode is not None:
                return self.returncode
            if timeout is None:
                self._reap(0)
                return self.returncode
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._reap(os.WNOHANG):
                    return self.returncode
                time.sleep(0.05)
            raise subprocess.TimeoutExpired(self.args, timeout)

        def terminate(self):
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        def kill(self):
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


    def _macos_spawn_disclaimed(argv, env, cwd):
        attr = ctypes.c_void_p()
        if _libc.posix_spawnattr_init(ctypes.byref(attr)) != 0:
            raise OSError("posix_spawnattr_init failed")

        try:
            if _libc.posix_spawnattr_setflags(ctypes.byref(attr), _POSIX_SPAWN_SETSID) != 0:
                raise OSError("posix_spawnattr_setflags(SETSID) failed")
            if _libc.responsibility_spawnattrs_setdisclaim(ctypes.byref(attr), 1) != 0:
                raise OSError("responsibility_spawnattrs_setdisclaim failed")

            argv_bytes = [a.encode() for a in argv]
            c_argv = (ctypes.c_char_p * (len(argv_bytes) + 1))(*argv_bytes, None)

            env_bytes = [f"{k}={v}".encode() for k, v in env.items()]
            c_envp = (ctypes.c_char_p * (len(env_bytes) + 1))(*env_bytes, None)

            pid = ctypes.c_int(0)
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                ret = _libc.posix_spawn(
                    ctypes.byref(pid),
                    argv[0].encode(),
                    None,  # file_actions
                    ctypes.byref(attr),
                    ctypes.cast(c_argv, ctypes.POINTER(ctypes.c_char_p)),
                    ctypes.cast(c_envp, ctypes.POINTER(ctypes.c_char_p)),
                )
            finally:
                os.chdir(old_cwd)

            if ret != 0:
                raise OSError(ret, f"posix_spawn failed: {os.strerror(ret)}")

            return _DisclaimedPopen(pid.value, argv)
        finally:
            _libc.posix_spawnattr_destroy(ctypes.byref(attr))


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


def _applescript_quote(value):
    # AppleScript-Stringliteral verlangt Double-Quotes mit \"-Escape.
    # Pythons repr() liefert oft Single-Quotes -> Syntaxfehler in osascript.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _elevated_command(binary_path):
    if sys.platform == "darwin":
        quoted_path = shlex.quote(binary_path)
        script = f"do shell script {_applescript_quote(quoted_path)} with administrator privileges"
        return ["osascript", "-e", script]

    if sys.platform.startswith("linux"):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return [binary_path]
        if shutil.which("sudo"):
            # Keep DISPLAY/XAUTHORITY and session vars for GUI apps.
            return ["sudo", "-E", "-S", binary_path]
        if shutil.which("pkexec"):
            return ["pkexec", binary_path]
        return [binary_path]

    return [binary_path]


def _start_process(base, name, requires_root=False):
    binary_path = _binary_path(base, name)
    command = _elevated_command(binary_path) if requires_root else [binary_path]

    env = os.environ.copy()
    if sys.platform.startswith("linux"):
        env.update(_linux_display_env())

    # macOS: TCC-Permission (Kamera, Accessibility) nur durch posix_spawn mit
    # disclaim-Flag korrekt vom .app-Bundle an den Subprocess weiterreichen.
    # Nicht fuer osascript-Aufrufe (requires_root): osascript laeuft als eigenes
    # signiertes Apple-Tool und braucht die Bundle-Identitaet nicht.
    if sys.platform == "darwin" and not requires_root:
        return _macos_spawn_disclaimed(command, env, base)

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

    # real_scanner braucht Root nur im Popup-Modus (fuer das `keyboard`-F12-Hotkey).
    # Im Streaming-Modus (WEIGHIN_SCANNER_CAMERA gesetzt) wird kein Hotkey
    # registriert -> als normaler User starten, damit der Subprocess die TCC-
    # Kamera-Berechtigung des .app-Bundles erbt (sonst eigene root-TCC ohne Grant).
    scanner_streaming = bool(os.environ.get("WEIGHIN_SCANNER_CAMERA", "").strip())
    scanner_needs_root = (
        not sys.platform.startswith("win") and not scanner_streaming
    )

    gui = _start_process(base, "gui", requires_root=False)
    weight = _start_process(base, "weight")
    scanner = _start_process(base, "real_scanner", requires_root=scanner_needs_root)

    try:
        gui.wait()
    finally:
        for process in (weight, scanner):
            _stop_process(process)


if __name__ == "__main__":
    main()
