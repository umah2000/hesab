"""Ways to get bytes to a printer. Each one sends a complete job or raises.

* ``tcp``     — raw socket to the printer's network port (usually 9100, "RAW/JetDirect").
* ``windows`` — the Windows spooler in RAW mode, for USB printers installed in Windows
                (needs ``pywin32``; the printer name as shown in Windows).
* ``serial``  — a COM port (needs ``pyserial``), e.g. ``COM3:9600``.
* ``file``    — append to a file; development and tests only.

None of these proves that a given printer model works — see the compatibility registry.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Protocol


class PrinterError(Exception):
    """Shown to the cashier (Persian), never contains internals or secrets."""


class Transport(Protocol):
    def send(self, data: bytes) -> None: ...


class TcpTransport:
    def __init__(self, address: str, timeout: float = 5.0) -> None:
        host, _, port = address.partition(":")
        self.host, self.port, self.timeout = host, int(port or 9100), timeout

    def send(self, data: bytes) -> None:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(data)
        except OSError as e:
            raise PrinterError(f"چاپگر شبکه ({self.host}:{self.port}) پاسخ نمی‌دهد") from e


class WindowsSpoolerTransport:
    def __init__(self, printer_name: str) -> None:
        self.name = printer_name

    def send(self, data: bytes) -> None:
        if sys.platform != "win32":
            raise PrinterError("چاپ از طریق Windows فقط روی ویندوز ممکن است")
        import win32print

        try:
            handle = win32print.OpenPrinter(self.name)
        except Exception as e:
            raise PrinterError(f"چاپگر «{self.name}» در ویندوز یافت نشد") from e
        try:
            win32print.StartDocPrinter(handle, 1, ("NEXTCAM receipt", None, "RAW"))
            try:
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, data)
                win32print.EndPagePrinter(handle)
            finally:
                win32print.EndDocPrinter(handle)
        except Exception as e:
            raise PrinterError(f"ارسال به چاپگر «{self.name}» ناموفق بود") from e
        finally:
            win32print.ClosePrinter(handle)


class SerialTransport:
    def __init__(self, address: str, timeout: float = 5.0) -> None:
        port, _, baud = address.partition(":")
        self.port, self.baud, self.timeout = port, int(baud or 9600), timeout

    def send(self, data: bytes) -> None:
        try:
            import serial
        except ImportError as e:
            raise PrinterError("پشتیبانی درگاه سریال نصب نشده است (pyserial)") from e
        try:
            with serial.Serial(self.port, self.baud, timeout=self.timeout) as port:
                port.write(data)
                port.flush()
        except Exception as e:
            raise PrinterError(f"درگاه {self.port} در دسترس نیست") from e


class FileTransport:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def send(self, data: bytes) -> None:
        with self.path.open("ab") as f:
            f.write(data)


def make(transport: str, address: str | None) -> Transport:
    if not address:
        raise PrinterError("نشانی چاپگر تنظیم نشده است")
    if transport == "tcp":
        return TcpTransport(address)
    if transport == "windows":
        return WindowsSpoolerTransport(address)
    if transport == "serial":
        return SerialTransport(address)
    if transport == "file":
        return FileTransport(address)
    raise PrinterError("برای این دستگاه چاپگری تنظیم نشده است")
