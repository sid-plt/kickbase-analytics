"""Read the installed Chrome version without launching a browser."""

from __future__ import annotations


import os
import re
import subprocess
import sys


def detect_chrome_major_version(browser_executable_path: str | None = None) -> int:
    """Select a driver matching Chrome, rather than the latest driver release.

    Windows executable metadata avoids launching Chrome with ``--version``,
    which can open an unwanted browser window on Windows.
    """
    if browser_executable_path is None:
        from undetected_chromedriver import find_chrome_executable

        browser_executable_path = find_chrome_executable()
    if not browser_executable_path:
        raise RuntimeError("Chrome was not found. Install Chrome or specify its executable path.")

    if sys.platform == "win32":
        environment = os.environ.copy()
        environment["KICKBASE_CHROME_EXECUTABLE"] = str(browser_executable_path)
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-Item -LiteralPath $env:KICKBASE_CHROME_EXECUTABLE).VersionInfo.ProductVersion"],
            capture_output=True, text=True, check=True, timeout=15,
            env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        result = subprocess.run(
            [str(browser_executable_path), "--version"],
            capture_output=True, text=True, check=True, timeout=15,
        )
    match = re.search(r"\b(\d+)\.\d+\.\d+\.\d+\b", result.stdout)
    if not match:
        raise RuntimeError("Could not read Chrome's version. Set CHROME_MAJOR_VERSION manually.")
    return int(match.group(1))
