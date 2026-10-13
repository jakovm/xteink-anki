"""Advertise the Xteink Anki HTTP API via mDNS/Bonjour on the LAN.

Service type: ``_xteink-anki._tcp`` (port from add-on config).
The API token is **not** published — devices still enter it manually.

Backends (first that works):
1. Apple ``dns-sd -R`` (macOS, no extra deps)
2. Optional ``zeroconf`` package (cross-platform if installed)
"""

from __future__ import annotations

import logging
import platform
import socket
import subprocess
import threading
from typing import Any, List, Optional

LOGGER = logging.getLogger(__name__)

# Without leading underscore for ESP32 MDNS.queryService("xteink-anki", "tcp").
SERVICE_TYPE_SHORT = "xteink-anki"
SERVICE_TYPE_DNS_SD = "_xteink-anki._tcp"
SERVICE_TYPE_ZEROCONF = "_xteink-anki._tcp.local."


def _primary_ipv4() -> Optional[str]:
    """Best-effort LAN IPv4 for Zeroconf address binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            if not addr.startswith("127."):
                return addr
    except OSError:
        pass
    return None


class MdnsAdvertiser:
    """Start/stop a single LAN service advertisement for the given port."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._zeroconf: Any = None
        self._info: Any = None
        self._backend = ""

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def active(self) -> bool:
        with self._lock:
            return self._process is not None or self._zeroconf is not None

    def start(
        self,
        port: int,
        *,
        enabled: bool = True,
        instance_name: str = "Xteink Anki",
        protocol_version: int = 3,
        addon_version: str = "",
    ) -> bool:
        """Register the service. Returns True if advertisement is running."""
        self.stop()
        if not enabled:
            LOGGER.info("mDNS advertise disabled in config")
            return False
        if port < 1 or port > 65535:
            LOGGER.warning("mDNS: invalid port %s", port)
            return False

        name = (instance_name or "Xteink Anki").strip() or "Xteink Anki"
        txt = {
            "path": "/",
            "proto": str(protocol_version),
        }
        if addon_version:
            txt["ver"] = str(addon_version)[:32]

        if platform.system() == "Darwin" and self._start_dns_sd(name, port, txt):
            return True
        if self._start_zeroconf(name, port, txt):
            return True

        LOGGER.warning(
            "mDNS advertise unavailable (install 'zeroconf' or use macOS dns-sd). "
            "Xteink devices must use a manual server URL."
        )
        return False

    def stop(self) -> None:
        with self._lock:
            proc = self._process
            self._process = None
            zc = self._zeroconf
            info = self._info
            self._zeroconf = None
            self._info = None
            self._backend = ""

        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            LOGGER.info("mDNS: stopped dns-sd advertiser")

        if zc is not None and info is not None:
            try:
                zc.unregister_service(info)
            except Exception:
                LOGGER.exception("mDNS: could not unregister zeroconf service")
            try:
                zc.close()
            except Exception:
                pass
            LOGGER.info("mDNS: stopped zeroconf advertiser")

    def _start_dns_sd(self, name: str, port: int, txt: dict) -> bool:
        # dns-sd -R Name Type Domain Port [key=value ...]
        cmd: List[str] = [
            "dns-sd",
            "-R",
            name,
            SERVICE_TYPE_DNS_SD,
            "local",
            str(port),
        ]
        for key, value in txt.items():
            cmd.append(f"{key}={value}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            LOGGER.debug("mDNS: dns-sd not found")
            return False
        except OSError:
            LOGGER.exception("mDNS: could not start dns-sd")
            return False

        # Give it a moment to fail fast on bad args.
        try:
            code = proc.poll()
            if code is not None:
                err = (proc.stderr.read() if proc.stderr else "") or f"exit {code}"
                LOGGER.warning("mDNS: dns-sd exited immediately: %s", err.strip())
                return False
        except Exception:
            pass

        with self._lock:
            self._process = proc
            self._backend = "dns-sd"
        LOGGER.info(
            "mDNS: advertising %s.%s on port %s via dns-sd",
            name,
            SERVICE_TYPE_DNS_SD,
            port,
        )
        return True

    def _start_zeroconf(self, name: str, port: int, txt: dict) -> bool:
        try:
            from zeroconf import ServiceInfo, Zeroconf  # type: ignore
        except ImportError:
            LOGGER.debug("mDNS: zeroconf package not installed")
            return False

        ip = _primary_ipv4()
        if not ip:
            LOGGER.warning("mDNS: no IPv4 address for zeroconf")
            return False

        try:
            properties = {k.encode("utf-8"): str(v).encode("utf-8") for k, v in txt.items()}
            info = ServiceInfo(
                SERVICE_TYPE_ZEROCONF,
                f"{name}.{SERVICE_TYPE_ZEROCONF}",
                addresses=[socket.inet_aton(ip)],
                port=port,
                properties=properties,
                server=f"{socket.gethostname().split('.')[0]}.local.",
            )
            zc = Zeroconf()
            zc.register_service(info)
        except Exception:
            LOGGER.exception("mDNS: zeroconf registration failed")
            return False

        with self._lock:
            self._zeroconf = zc
            self._info = info
            self._backend = "zeroconf"
        LOGGER.info(
            "mDNS: advertising %s on %s:%s via zeroconf",
            name,
            ip,
            port,
        )
        return True
