"""Wiesn-Agent — CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from wiesn_agent.config_model import WiesnConfig
from wiesn_agent.workflow import build_workflow

logger = logging.getLogger("wiesn_agent")


async def run_once(config: WiesnConfig) -> None:
    """Single run: Check all portals once."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=config.browser.headless,
            slow_mo=config.browser.slow_mo,
        )
        page = await browser.new_page()

        logger.info("Starting single check of all portals...")
        workflow, _ = build_workflow(config, page)
        events = await workflow.run("start")

        logger.info("Workflow complete. Status: %s", events.get_final_state())
        for output in events.get_outputs():
            logger.info("Result: %s", output)

        await browser.close()


async def run_watch(config: WiesnConfig) -> None:
    """Watch mode: Check at regular intervals."""
    from playwright.async_api import async_playwright

    interval = config.monitoring.check_interval_minutes * 60
    portal_hashes: dict[str, str] = {}

    logger.info(
        "Starting watch mode every %d minutes (%d portals)...",
        config.monitoring.check_interval_minutes,
        len(config.enabled_portale()),
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=config.browser.headless,
            slow_mo=config.browser.slow_mo,
        )
        page = await browser.new_page()

        run_count = 0
        while True:
            run_count += 1
            logger.info("=== Run #%d ===", run_count)

            try:
                workflow, portal_hashes = build_workflow(config, page, portal_hashes)
                events = await workflow.run("start")

                logger.info("Status: %s", events.get_final_state())
                for output in events.get_outputs():
                    logger.info("Ergebnis: %s", output)

            except Exception as e:
                logger.error("Error in run #%d: %s", run_count, e)

            logger.info("Next check in %d minutes...", config.monitoring.check_interval_minutes)
            await asyncio.sleep(interval)


def run_devui(config: WiesnConfig) -> None:
    """Start the DevUI for workflow visualization (no browser needed)."""
    # DevUI only needs the workflow graph structure, not an actual browser page.
    workflow, _ = build_workflow(config, None)

    try:
        from agent_framework_devui import serve

        logger.info("Starting DevUI on http://localhost:8080 ...")
        serve(entities=[workflow], auto_open=True)
    except ImportError:
        logger.error(
            "DevUI not installed. Install with: uv pip install --prerelease=allow agent-framework-devui"
        )
        sys.exit(1)


def run_web(config: WiesnConfig, port: int = 5000, host: str = "127.0.0.1") -> None:
    """Start the web dashboard UI."""
    import uvicorn

    from wiesn_agent.api import create_app

    create_app()
    logger.info("Starting Wiesn-Agent Dashboard on http://%s:%d ...", host, port)
    uvicorn.run("wiesn_agent.api:app", host=host, port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wiesn-Agent — Oktoberfest Reservation Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  wiesn-agent once              Single check with AI agents (needs GITHUB_TOKEN)
  wiesn-agent watch             Watch mode with AI (every X minutes)
  wiesn-agent web               Web dashboard UI (http://localhost:5000)
  wiesn-agent devui             DevUI for workflow visualization
        """,
    )
    parser.add_argument(
        "mode",
        choices=["once", "watch", "web", "devui"],
        help="Operating mode: once | watch | web | devui",
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="Path to .env file (default: .env)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind web server (default: 127.0.0.1, Docker auto-detects 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for web server (default: 5000)",
    )

    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # .env laden
    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)
        logger.debug("Environment variables loaded from %s", env_path)

    # Config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("Config file '%s' not found!", config_path)
        logger.error("Copy config.example.yaml to config.yaml and adjust it.")
        sys.exit(1)

    config = WiesnConfig.from_yaml(config_path)
    logger.info("Config loaded: %d portals, %d preferred dates",
                len(config.enabled_portale()), len(config.reservierung.wunsch_tage))

    # Run mode
    if args.mode == "once":
        asyncio.run(run_once(config))
    elif args.mode == "watch":
        asyncio.run(run_watch(config))
    elif args.mode == "web":
        # Auto-detect Docker: bind 0.0.0.0 if running inside a container
        host = args.host
        if host is None:
            host = "0.0.0.0" if Path("/.dockerenv").exists() else "127.0.0.1"
        # Pass config path to API module so it uses the correct file
        import wiesn_agent.api as api_mod
        api_mod.CONFIG_PATH = config_path.resolve()
        run_web(config, port=args.port, host=host)
    elif args.mode == "devui":
        run_devui(config)


if __name__ == "__main__":
    main()
