"""Bootable USB builder API for Wolfpack enterprise migration.

Wraps appliance/build-peer-usb.sh so operators can create a migration USB
from the Jarvis desktop without touching the shell.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "appliance" / "build-peer-usb.sh"
BUILD_LOG_DIR = REPO_ROOT / "data" / "usb-build-logs"

router = APIRouter(tags=["usb"])

# job_id -> job dict
_jobs: dict[str, dict[str, Any]] = {}

# How the service should locate the authenticated Kimi Code CLI on alpha.
_KIMI_CODE_HOME = Path.home() / ".kimi-code"


class USBBuildRequest(BaseModel):
    target: str = Field(..., description="Block device path, e.g. /dev/sdb")
    persona: str = Field(default="ledger", description="Wolfpack persona for the peer.")
    hub_id: str | None = Field(default=None, description="Mesh hub_id; defaults to hub-<persona>.")
    dry_run: bool = Field(default=False, description="Build ISO only; do not write to USB.")


class DeployHubRequest(BaseModel):
    wifi: bool = Field(default=False, description="Create a WiFi hotspot for netboot clients.")
    ssid: str | None = Field(default=None, description="Hotspot SSID; defaults to Wolfpack-Setup.")
    psk: str | None = Field(default=None, description="Hotspot PSK; defaults to kingking1007.")


class USBDevice(BaseModel):
    path: str
    name: str
    size: str
    model: str | None = None
    vendor: str | None = None
    removable: bool = True


def _is_usb_device(dev_path: str) -> bool:
    """Check whether a block device is removable and connected via USB."""
    name = Path(dev_path).name
    tran_path = Path(f"/sys/block/{name}/device/type")
    # Prefer the udev/lsblk TRAN property when available.
    try:
        out = subprocess.check_output(
            ["lsblk", "-dno", "NAME,TRAN", dev_path],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if "usb" in out.lower():
            return True
    except Exception:
        pass
    # Fallback: require the removable flag.
    removable_path = Path(f"/sys/block/{name}/removable")
    try:
        if removable_path.read_text().strip() == "1":
            return True
    except Exception:
        pass
    return False


def _list_usb_devices() -> list[dict[str, Any]]:
    """List removable USB block devices via lsblk."""
    if platform.system() != "Linux":
        return []
    try:
        out = subprocess.check_output(
            ["lsblk", "-J", "-d", "-o", "NAME,PATH,SIZE,TYPE,TRAN,MODEL,VENDOR"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        data = json.loads(out)
    except Exception:
        return []

    devices: list[dict[str, Any]] = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        tran = (dev.get("tran") or "").lower()
        if tran != "usb":
            # secondary check via sysfs removable flag
            name = dev.get("name", "")
            try:
                if Path(f"/sys/block/{name}/removable").read_text().strip() != "1":
                    continue
            except Exception:
                continue
        devices.append({
            "path": dev.get("path", f"/dev/{dev.get('name', '')}"),
            "name": dev.get("name", ""),
            "size": dev.get("size", "?"),
            "model": dev.get("model") or None,
            "vendor": dev.get("vendor") or None,
            "removable": True,
        })
    return devices


def _read_tail(path: Path, lines: int = 120) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    all_lines = text.splitlines()
    return "\n".join(all_lines[-lines:])


@router.get("/api/usb/devices")
async def list_usb_devices():
    """List removable USB block devices suitable for imaging."""
    return {"devices": _list_usb_devices()}


@router.post("/api/usb/build")
async def start_usb_build(req: USBBuildRequest):
    """Start a bootable USB build in the background.

    Requires the jarvis service to have a passwordless-sudo rule for
    appliance/build-peer-usb.sh, or the call will fail with a clear message.
    """
    if not SCRIPT_PATH.exists():
        raise HTTPException(status_code=500, detail="USB build script not found")
    if shutil.which("sudo") is None:
        raise HTTPException(status_code=500, detail="sudo is not available on this host")

    target = req.target
    if not req.dry_run:
        if not target or not Path(target).exists() or not Path(target).is_block_device():
            raise HTTPException(status_code=400, detail=f"Invalid block device: {target}")
        if not _is_usb_device(target):
            raise HTTPException(status_code=400, detail=f"{target} is not a removable USB device")

    job_id = f"usb-{uuid.uuid4().hex[:12]}"
    BUILD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = BUILD_LOG_DIR / f"{job_id}.log"

    persona = req.persona or "ledger"
    hub_id = req.hub_id or f"hub-{persona}"

    # The service runs as an unprivileged user; a passwordless-sudo wrapper
    # (/usr/local/bin/wolfpack-build-usb) handles elevation.
    inner_args = ["sudo", "--non-interactive", "/usr/local/bin/wolfpack-build-usb"]
    if req.dry_run:
        inner_args.append("--dry-run")
        inner_args.extend([persona, hub_id])
    else:
        inner_args.extend(["--yes", target, persona, hub_id])

    # Wrap in `script` so the subprocess gets a pseudo-TTY; this makes bash/echo
    # and `dd status=progress` line-buffered so the log updates live.
    inner_cmd = " ".join(shlex.quote(a) for a in inner_args)
    args = ["script", "-q", "-c", inner_cmd, "/dev/null"]

    env = os.environ.copy()
    env["KIMI_CODE_HOME"] = str(_KIMI_CODE_HOME)
    env["CACHE_DIR"] = str(REPO_ROOT / ".cache" / "appliance")

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    _jobs[job_id] = {
        "proc": proc,
        "log_path": log_path,
        "target": target,
        "persona": persona,
        "hub_id": hub_id,
        "dry_run": req.dry_run,
        "started_at": time.time(),
        "status": "running",
        "returncode": None,
        "error": None,
    }

    async def _collect_output() -> None:
        log_path.write_bytes(b"")
        assert proc.stdout is not None
        with open(log_path, "ab") as logf:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                logf.write(chunk)
        await proc.wait()
        job = _jobs.get(job_id)
        if job:
            job["returncode"] = proc.returncode
            job["status"] = "done" if proc.returncode == 0 else "failed"
            if proc.returncode != 0:
                job["error"] = _read_tail(log_path, 20)

    asyncio.create_task(_collect_output())

    return {
        "ok": True,
        "job_id": job_id,
        "target": target,
        "persona": persona,
        "hub_id": hub_id,
        "dry_run": req.dry_run,
        "status": "running",
    }


@router.post("/api/usb/deploy-hub")
async def deploy_netboot_hub(req: DeployHubRequest):
    """Turn this machine into a Wolfpack netboot hub from the inserted USB.

    Requires the jarvis service to have a passwordless-sudo rule for
    /usr/local/bin/wolfpack-netboot-hub.
    """
    if shutil.which("sudo") is None:
        raise HTTPException(status_code=500, detail="sudo is not available on this host")

    job_id = f"hub-{uuid.uuid4().hex[:12]}"
    BUILD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = BUILD_LOG_DIR / f"{job_id}.log"

    args = ["sudo", "--non-interactive", "/usr/local/bin/wolfpack-netboot-hub"]
    if req.wifi:
        args.append("--wifi")
    if req.ssid:
        args.extend(["--ssid", req.ssid])
    if req.psk:
        args.extend(["--psk", req.psk])

    inner_cmd = " ".join(shlex.quote(a) for a in args)
    script_args = ["script", "-q", "-c", inner_cmd, "/dev/null"]

    proc = await asyncio.create_subprocess_exec(
        *script_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    _jobs[job_id] = {
        "proc": proc,
        "log_path": log_path,
        "target": "netboot-hub",
        "persona": "hub",
        "hub_id": "hub",
        "dry_run": False,
        "started_at": time.time(),
        "status": "running",
        "returncode": None,
        "error": None,
    }

    async def _collect_output() -> None:
        log_path.write_bytes(b"")
        assert proc.stdout is not None
        with open(log_path, "ab") as logf:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                logf.write(chunk)
        await proc.wait()
        job = _jobs.get(job_id)
        if job:
            job["returncode"] = proc.returncode
            job["status"] = "done" if proc.returncode == 0 else "failed"
            if proc.returncode != 0:
                job["error"] = _read_tail(log_path, 20)

    asyncio.create_task(_collect_output())

    return {
        "ok": True,
        "job_id": job_id,
        "wifi": req.wifi,
        "status": "running",
    }


@router.get("/api/usb/build/status/{job_id}")
async def usb_build_status(job_id: str):
    """Poll the status and recent log of a USB build or hub-deploy job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {
        "job_id": job_id,
        "status": job["status"],
        "target": job["target"],
        "persona": job["persona"],
        "hub_id": job["hub_id"],
        "dry_run": job["dry_run"],
        "returncode": job["returncode"],
        "error": job["error"],
        "log": _read_tail(job["log_path"]),
    }


@router.get("/api/usb/build/jobs")
async def list_usb_build_jobs():
    """List running/completed USB build jobs."""
    return {
        "jobs": [
            {
                "job_id": jid,
                "status": j["status"],
                "target": j["target"],
                "persona": j["persona"],
                "hub_id": j["hub_id"],
                "dry_run": j["dry_run"],
                "returncode": j["returncode"],
            }
            for jid, j in _jobs.items()
        ]
    }
