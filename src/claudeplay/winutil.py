'''small windows helpers: single-instance mutex, port ownership, clipboard, hidden subprocesses'''

import ctypes
import re
import socket
import subprocess

CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183


def run_hidden(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    ''' run a helper command without flashing a console window '''
    return subprocess.run(args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, **kwargs)


class SingleInstance:
    ''' a named mutex held for the life of the process; a second holder of the same name is refused '''

    def __init__(self, name: str):
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._handle = kernel32.CreateMutexW(None, False, f'Local\\{name}')
        self.acquired = bool(self._handle) and kernel32.GetLastError() != ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
        self.acquired = False


def port_in_use(host: str, port: int) -> bool:
    ''' true if something is already listening on host:port '''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def port_owner(port: int) -> str:
    ''' describe the process listening on a local tcp port, e.g. 'python.exe (pid 1234)' '''
    out = run_hidden(['netstat', '-ano', '-p', 'TCP']).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == 'LISTENING' and parts[1].rsplit(':', 1)[-1] == str(port):
            pid = parts[4]
            tasks = run_hidden(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH']).stdout.strip()
            match = re.match(r'"([^"]+)"', tasks)
            return f'{match.group(1) if match else "unknown process"} (pid {pid})'
    return 'an unknown process'


def pid_alive(pid: int) -> bool:
    out = run_hidden(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH']).stdout
    return f'"{pid}"' in out


def copy_to_clipboard(text: str) -> None:
    subprocess.run(['clip'], input=text.encode('utf-8'), creationflags=CREATE_NO_WINDOW, check=False)


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_int64),
        ('PerJobUserTimeLimit', ctypes.c_int64),
        ('LimitFlags', ctypes.c_uint32),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', ctypes.c_uint32),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', ctypes.c_uint32),
        ('SchedulingClass', ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
        'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', _BasicLimits),
        ('IoInfo', _IoCounters),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class KillOnCloseJob:
    ''' put this process in a job that kills every member when the process dies, however it dies '''

    def __init__(self):
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self._handle = kernel32.CreateJobObjectW(None, None)
        self.active = False
        if not self._handle:
            return
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            self._handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits))
        # processes started after this point inherit membership, so call this before spawning anything
        self.active = bool(ok) and bool(kernel32.AssignProcessToJobObject(self._handle, kernel32.GetCurrentProcess()))
