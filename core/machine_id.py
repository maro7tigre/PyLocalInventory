"""
Machine ID generation for license binding.

Generates a reasonably stable identifier for the Main PC based on hardware
characteristics. The ID should be stable across reboots but unique enough
to prevent casual license copying between machines.
"""
import hashlib
import platform
import subprocess
import uuid
import logging

logger = logging.getLogger(__name__)


def _get_windows_machine_guid():
    """Read MachineGuid from Windows registry (stable across hardware changes)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return value.strip()
    except Exception:
        return None


def _get_windows_product_id():
    """Read ProductId from Windows registry as fallback."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        value, _ = winreg.QueryValueEx(key, "ProductId")
        winreg.CloseKey(key)
        return value.strip()
    except Exception:
        return None


def _get_mac_addresses():
    """Get all non-virtual MAC addresses."""
    macs = []
    try:
        for interface, addrs in uuid.getnode().__dict__.items():
            pass
    except Exception:
        pass

    try:
        import netifaces
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_LINK in addrs:
                for addr in addrs[netifaces.AF_LINK]:
                    mac = addr.get('addr', '').upper()
                    if mac and mac != '00:00:00:00:00:00':
                        macs.append(mac)
    except Exception:
        pass

    if not macs:
        node = uuid.getnode()
        if node != uuid.getnode():
            mac = ':'.join(f'{(node >> 8 * i) & 0xFF:02X}' for i in range(5, -1, -1))
            if mac != '00:00:00:00:00:00':
                macs.append(mac)

    return macs


def _get_cpu_info():
    """Get CPU identifier."""
    try:
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['wmic', 'cpu', 'get', 'ProcessorId'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if len(lines) > 1:
                return lines[1]
        else:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('Serial') or line.startswith('processor'):
                        return line.split(':')[1].strip()
    except Exception:
        pass
    return platform.processor()


def _get_motherboard_serial():
    """Get motherboard serial number (Windows)."""
    try:
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['wmic', 'baseboard', 'get', 'SerialNumber'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if len(lines) > 1:
                return lines[1]
    except Exception:
        pass
    return None


def _get_disk_serial():
    """Get primary disk serial number."""
    try:
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['wmic', 'diskdrive', 'get', 'SerialNumber'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if len(lines) > 1:
                return lines[1]
    except Exception:
        pass
    return None


def generate_machine_id() -> str:
    """
    Generate a stable machine ID for license binding.

    Combines multiple hardware identifiers and hashes them to produce
    a consistent 32-character hexadecimal string.

    Returns:
        32-character hexadecimal machine ID string
    """
    components = []

    machine_guid = _get_windows_machine_guid()
    if machine_guid:
        components.append(f"machine_guid:{machine_guid}")

    product_id = _get_windows_product_id()
    if product_id:
        components.append(f"product_id:{product_id}")

    macs = _get_mac_addresses()
    if macs:
        components.append(f"macs:{','.join(sorted(macs))}")

    cpu_id = _get_cpu_info()
    if cpu_id:
        components.append(f"cpu:{cpu_id}")

    mb_serial = _get_motherboard_serial()
    if mb_serial and mb_serial not in ('', 'To Be Filled By O.E.M.', 'Default string'):
        components.append(f"motherboard:{mb_serial}")

    disk_serial = _get_disk_serial()
    if disk_serial:
        components.append(f"disk:{disk_serial}")

    if not components:
        fallback = f"{platform.node()}:{platform.machine()}:{platform.processor()}"
        components.append(f"fallback:{fallback}")
        logger.warning("Using fallback machine ID components: %s", fallback)

    combined = '|'.join(sorted(components))
    machine_id = hashlib.sha256(combined.encode('utf-8')).hexdigest()[:32]

    logger.info("Generated machine ID: %s (from %d components)", machine_id, len(components))
    return machine_id


def get_cached_machine_id(cache_path: str | None = None) -> str:
    """
    Get machine ID with optional caching to a file.

    Args:
        cache_path: Optional path to cache file. If provided, the machine ID
                   will be cached to this file on first generation.

    Returns:
        Machine ID string
    """
    import os

    if cache_path:
        try:
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    cached = f.read().strip()
                    if cached and len(cached) == 32:
                        return cached
        except Exception:
            pass

    machine_id = generate_machine_id()

    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'w') as f:
                f.write(machine_id)
        except Exception as e:
            logger.warning("Failed to cache machine ID: %s", e)

    return machine_id