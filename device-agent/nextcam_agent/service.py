"""Windows service wrapper (pywin32). Not exercised in CI: it must be installed and
tested on the register's Windows PC (see docs/install/device-agent.md).

    python -m nextcam_agent.service install   # as Administrator
    python -m nextcam_agent.service start
"""

from __future__ import annotations

import sys
import threading

if sys.platform != "win32":  # pragma: no cover - import guard for other systems
    raise SystemExit("The Windows service wrapper only runs on Windows")

import servicemanager
import win32event
import win32service
import win32serviceutil

from nextcam_agent.cli import build_agent, setup_logging
from nextcam_agent.localapi import serve_in_background


class AgentService(win32serviceutil.ServiceFramework):  # type: ignore[misc]
    _svc_name_ = "NextcamAgent"
    _svc_display_name_ = "NEXTCAM Device Agent"
    _svc_description_ = "چاپ فیش و کشوی پول صندوق NEXTCAM"

    def __init__(self, args: list[str]) -> None:
        super().__init__(args)
        self.stop_event = threading.Event()
        self.wait_handle = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        win32event.SetEvent(self.wait_handle)

    def SvcDoRun(self) -> None:
        servicemanager.LogInfoMsg("NEXTCAM Device Agent starting")
        setup_logging()
        agent = build_agent()
        srv = serve_in_background(agent.cfg.status_port, agent.snapshot)
        try:
            agent.run(self.stop_event)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(AgentService)
