import shutil
import subprocess


class AdbBridge:
    def __init__(self, adb_path: str | None = None):
        self.adb = adb_path or shutil.which('adb') or 'adb.exe'

    def is_device_connected(self) -> bool:
        try:
            res = subprocess.run([self.adb, 'devices'], capture_output=True, text=True)
            lines = [line.strip() for line in res.stdout.strip().split('\n')[1:] if line.strip()]
            return any('\tdevice' in line or line.endswith(' device') for line in lines)
        except Exception:
            return False

    def forward_port(self, host_port: int = 7070, device_port: int = 7070) -> bool:
        try:
            res = subprocess.run(
                [self.adb, 'forward', f'tcp:{host_port}', f'tcp:{device_port}'],
                capture_output=True,
                text=True,
            )
            return res.returncode == 0
        except Exception:
            return False
