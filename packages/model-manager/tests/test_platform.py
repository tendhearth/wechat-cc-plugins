from model_manager.platform import platform_from, current_platform

def test_mac_arm():
    assert platform_from("Darwin", "arm64") == "mac-arm64"

def test_mac_intel():
    assert platform_from("Darwin", "x86_64") == "mac-x64"

def test_windows():
    assert platform_from("Windows", "AMD64") == "win-x64"

def test_linux():
    assert platform_from("Linux", "x86_64") == "linux-x64"

def test_unknown_falls_back_to_linux_x64():
    assert platform_from("Plan9", "sparc") == "linux-x64"

def test_current_platform_returns_known_key():
    assert current_platform() in {"mac-arm64", "mac-x64", "win-x64", "linux-x64"}
