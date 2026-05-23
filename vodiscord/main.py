"""vodiscord entry point.

This is the v0.1 walking-skeleton: pops a hello box and exits. Real wiring
(qasync, Discord client, UI) lands in subsequent tasks.
"""

import multiprocessing
import os
import sys


def _early_windows_setup() -> None:
    """stdout/stderr None-guards + os.add_dll_directory patch.

    Lifted from chimptype-ui. Required when running as a Nuitka-built
    --windows-console-mode=disable binary: the process has no console, so
    sys.stdout/sys.stderr are None, and curl_cffi/davey wheels register
    relative DLL paths that os.add_dll_directory rejects with WinError 87.
    """
    if sys.platform != "win32":
        return
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if hasattr(os, "add_dll_directory"):
        _orig_add = os.add_dll_directory

        def _safe_add(path: str):
            return _orig_add(os.path.abspath(path))

        os.add_dll_directory = _safe_add  # type: ignore[assignment]


def main() -> int:
    multiprocessing.freeze_support()
    _early_windows_setup()

    from PySide6.QtWidgets import QApplication, QMessageBox

    from vodiscord import __app_name__, __version__

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName(__app_name__)

    box = QMessageBox()
    box.setWindowTitle(__app_name__)
    box.setText(f"{__app_name__} {__version__} — walking skeleton.\nReal UI lands next.")
    box.exec()

    os._exit(0)


if __name__ == "__main__":
    main()
