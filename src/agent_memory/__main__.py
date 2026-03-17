"""CLI entry point for agent-memory MCP server."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from agent_memory.config import load_config

logger = logging.getLogger("agent_memory")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-memory-server",
        description="MCP memory server for AI agents",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config YAML file",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=None,
        help="Transport type (overrides config)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="HTTP host (overrides config)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port (overrides config)",
    )
    return parser.parse_args(argv)


async def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = load_config(args.config)

    # CLI overrides
    if args.transport:
        config.server.transport = args.transport
    if args.host:
        config.server.http_host = args.host
    if args.port:
        config.server.http_port = args.port

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Validate HTTP security
    if config.server.transport == "http":
        if config.server.http_host != "127.0.0.1" and not config.server.auth_token:
            logger.error(
                "Refusing to bind to %s without auth_token set. "
                "Set server.auth_token or use 127.0.0.1",
                config.server.http_host,
            )
            sys.exit(1)

    # Lazy imports to keep startup fast
    from agent_memory.embedding import create_provider
    from agent_memory.server import create_mcp_server
    from agent_memory.storage import SQLiteStorage

    # Initialize storage
    storage = SQLiteStorage(config.storage, embedding_dim=config.embedding.dimensions)
    await storage.initialize()

    # Initialize embedding provider
    embedding_provider = create_provider(config.embedding)

    # Initialize consolidation (if configured)
    consolidation_engine = None
    if config.consolidation.provider and config.consolidation.provider != "none":
        from agent_memory.consolidation.engine import ConsolidationEngine
        from agent_memory.consolidation.llm import create_llm_provider

        llm_provider = create_llm_provider(config.consolidation)
        consolidation_engine = ConsolidationEngine(
            storage=storage,
            llm_provider=llm_provider,
            config=config.consolidation,
        )

    # Initialize ingestion processor
    from agent_memory.ingestion.processor import IngestionProcessor

    ingestion_processor = IngestionProcessor(
        storage=storage,
        embedding_provider=embedding_provider,
        llm_provider=consolidation_engine.llm_provider if consolidation_engine else None,
        config=config.ingestion,
    )

    # Create and run MCP server
    mcp_server = create_mcp_server(
        storage=storage,
        embedding_provider=embedding_provider,
        consolidation_engine=consolidation_engine,
        ingestion_processor=ingestion_processor,
        config=config,
    )

    # Start auto-consolidation if configured
    if consolidation_engine and config.consolidation.auto_interval_minutes > 0:
        asyncio.create_task(consolidation_engine.start_auto_consolidation())
        logger.info(
            "Auto-consolidation enabled (every %d min)",
            config.consolidation.auto_interval_minutes,
        )

    logger.info(
        "Starting agent-memory server (transport=%s)", config.server.transport
    )

    try:
        if config.server.transport == "stdio":
            await mcp_server.run_stdio_async()
        else:
            await mcp_server.run_sse_async(
                host=config.server.http_host,
                port=config.server.http_port,
            )
    finally:
        await storage.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
