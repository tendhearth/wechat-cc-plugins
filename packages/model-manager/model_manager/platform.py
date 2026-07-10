"""Current-OS detection, reduced to a small set of platform keys."""
import platform as _platform


def platform_from(system: str, machine: str) -> str:
    system = (system or "").lower()
    machine = (machine or "").lower()
    if system == "darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    if system == "windows":
        return "win-x64"
    if system == "linux":
        return "linux-x64"
    return "linux-x64"  # conservative fallback


def current_platform() -> str:
    return platform_from(_platform.system(), _platform.machine())
