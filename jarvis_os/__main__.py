"""Entry point for the Jarvis OS runtime."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from jarvis_os.config import load_config
from jarvis_os.core.runtime import Runtime
from jarvis_os.core.scheduler import ScheduledTask
from jarvis_os.interfaces.headless.cli import HeadlessCLI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _import_web_gui():
    """Lazy import so the package can be imported without GUI extras."""
    try:
        from jarvis_os.interfaces.gui.app import WebGUI
    except ImportError as exc:
        logger.error(
            "GUI dependencies not installed. Install with: pip install -e '.[gui]'"
        )
        raise SystemExit(1) from exc
    return WebGUI


def _import_voice_interface():
    """Lazy import so the package can be imported without voice extras."""
    try:
        from jarvis_os.interfaces.voice.interface import VoiceInterface
    except ImportError as exc:
        logger.error(
            "Voice dependencies not installed. Install with: pip install -e '.[voice]'"
        )
        raise SystemExit(1) from exc
    return VoiceInterface


async def run_once(runtime: Runtime, goal: str, agent: str) -> None:
    result = await runtime.run_with_agent(goal, agent_type=agent)
    print(result.get("summary") or result.get("answer", "Done."))
    for key in ("results", "steps", "observations"):
        if key in result and result[key]:
            print(f"\n{key.upper()}:")
            for item in result[key]:
                print(f"- {item}")
    runtime.shutdown()


async def run_cli(runtime: Runtime, agent: str) -> None:
    interface = HeadlessCLI(runtime, default_agent=agent)
    await interface.run()


async def _run_web_server(runtime: Runtime, host: str, port: int, config_path: Path) -> None:
    """Start the web dashboard as a background task (used by --hub in CLI/voice mode)."""
    WebGUI = _import_web_gui()
    interface = WebGUI(runtime, default_agent="simple", config_path=config_path)
    await interface.run(host=host, port=port)


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Jarvis OS")
    parser.add_argument("--config", "-c", type=Path, default=Path("config/jarvis.yaml"))
    parser.add_argument("--interface", "-i", choices=["cli", "gui", "voice"], default="cli")
    parser.add_argument("--port", "-p", type=int, default=None, help="Port for the web GUI (overrides config network.gui_port)")
    parser.add_argument("--host", type=str, default=None, help="Host for the web GUI (overrides config network.gui_host; use 0.0.0.0 for LAN)")
    parser.add_argument("--agent", "-a", choices=["simple", "react", "codeact", "autonomous"], default="simple", help="Agent execution mode")
    parser.add_argument("--goal", "-g", type=str, default=None, help="Run a single goal and exit")
    parser.add_argument("--directive", "-d", type=str, default=None, help="Run a high-level directive autonomously (same as --goal --agent autonomous)")
    parser.add_argument("--schedule", "-s", type=str, default=None, help="Schedule a recurring goal (format: id:seconds:goal)")
    parser.add_argument("--hub", action="store_true", help="Enable hub mode: shared memory, job queue, mesh, inbox, and share-bus coordination")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        logger.error("Config not found: %s", args.config)
        print(f"Config not found: {args.config}", file=sys.stderr)
        print("Copy config/example.yaml to config/jarvis.yaml and edit it.", file=sys.stderr)
        return 1

    if args.hub:
        config.hub.enabled = True

    logging.getLogger().setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    runtime = Runtime(config)
    await runtime.start_scheduler()
    await runtime.start_hub_services()

    agent = "autonomous" if args.directive else args.agent
    goal = args.directive or args.goal
    web_task: asyncio.Task | None = None

    try:
        if goal:
            await run_once(runtime, goal, agent)
            return 0

        if args.schedule:
            try:
                task_id, interval, scheduled_goal = args.schedule.split(":", 2)
            except ValueError:
                print("--schedule format: id:seconds:goal", file=sys.stderr)
                return 1
            runtime.schedule(ScheduledTask(id=task_id, goal=scheduled_goal, interval_seconds=int(interval)))
            logger.info("Scheduled %s every %s seconds: %s", task_id, interval, scheduled_goal)
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            return 0

        if args.interface == "cli":
            if config.hub.enabled and config.hub.auto_start_web:
                # Hub mode: run the web dashboard as the primary surface so the node
                # stays alive without an interactive terminal (e.g. under systemd).
                host = args.host if args.host is not None else config.network.gui_host
                port = args.port if args.port is not None else config.network.gui_port
                await _run_web_server(runtime, host, port, args.config)
            else:
                await run_cli(runtime, agent)
        elif args.interface == "gui":
            WebGUI = _import_web_gui()
            interface = WebGUI(runtime, default_agent=agent, config_path=args.config)
            # CLI flags override config; config supplies the default so host/port
            # are a real setting, not hardcoded.
            host = args.host if args.host is not None else config.network.gui_host
            port = args.port if args.port is not None else config.network.gui_port
            await interface.run(host=host, port=port)
        elif args.interface == "voice":
            if config.hub.enabled and config.hub.auto_start_web:
                host = args.host if args.host is not None else config.network.gui_host
                port = args.port if args.port is not None else config.network.gui_port
                web_task = asyncio.get_running_loop().create_task(
                    _run_web_server(runtime, host, port, args.config)
                )
            VoiceInterface = _import_voice_interface()
            interface = VoiceInterface(runtime)
            await interface.run()
        else:
            logger.error("Interface '%s' is not implemented yet.", args.interface)
            return 1
    finally:
        if web_task is not None and not web_task.done():
            web_task.cancel()
            try:
                await web_task
            except asyncio.CancelledError:
                pass
        await runtime.stop_hub_services()
        await runtime.stop_scheduler()
        runtime.shutdown()

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
