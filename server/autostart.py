import os
import sys
import logging

logger = logging.getLogger("OpenDisplay.Autostart")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "OpenDisplay"


def get_executable_command() -> str:
    """Returns the properly quoted executable command for the current installation."""
    if getattr(sys, "frozen", False):
        exe_path = sys.executable
        return f'"{exe_path}"'
    else:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dist_exe = os.path.join(root_dir, "dist", "OpenDisplay", "OpenDisplay.exe")
        if os.path.exists(dist_exe):
            return f'"{dist_exe}"'
        server_py = os.path.join(root_dir, "opendisplay_server.py")
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        return f'"{pythonw}" "{server_py}"'


def is_autostart_enabled() -> bool:
    """Checks whether OpenDisplay is registered in HKCU Run key."""
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"Failed querying autostart registry: {e}")
        return False


def set_autostart(enable: bool) -> bool:
    """Enables or disables OpenDisplay startup in HKCU Run key."""
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                cmd = get_executable_command()
                winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_SZ, cmd)
                logger.info(f"Registered autostart command: {cmd}")
            else:
                try:
                    winreg.DeleteValue(key, APP_VALUE_NAME)
                    logger.info("Removed autostart registration.")
                except FileNotFoundError:
                    pass
            return True
    except Exception as e:
        logger.error(f"Failed setting autostart registry to {enable}: {e}")
        return False
