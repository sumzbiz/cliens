"""Administrative commands (materials seeding) invoked via ``python -m app.cli``.

Kept deliberately small — argparse and a handful of coroutines rather than a CLI
framework, because the only operational task is seeding reference data.

    python -m app.cli seed-materials      (or: npm run db:seed)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import load_settings_or_exit
from app.core.database import dispose_database, init_database
from app.core.logging import configure_logging, get_logger, new_request_id, request_context
from app.repositories.materials import MaterialRepository, load_seed_materials

logger = get_logger(__name__)


async def seed_materials() -> int:
    """Load the bundled material catalogue into the database.

    Idempotent: re-running updates existing rows by code rather than failing, so a
    revised resistance value can be applied by re-seeding.

    Returns:
        Process exit code: 0 on success, 1 on failure.
    """
    settings = load_settings_or_exit()
    configure_logging(settings)
    database = init_database(settings)

    try:
        with request_context(new_request_id()):
            try:
                materials = load_seed_materials()
            except (OSError, ValueError) as error:
                logger.error("materials_seed_file_unreadable", error=str(error))
                sys.stderr.write(f"Could not read the material seed file: {error}\n")
                return 1

            async with database.session_factory() as session:
                repository = MaterialRepository(session)
                written = await repository.upsert_many(materials)
                await session.commit()
                total = await repository.count()

            sys.stdout.write(f"Seeded {written} materials. Catalogue now holds {total} entries.\n")
            return 0
    finally:
        await dispose_database()


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Administrative commands for Climate Lien Score.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "seed-materials",
        help="Load the bundled material catalogue into the database (idempotent).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Returns:
        Process exit code.
    """
    arguments = build_parser().parse_args(argv)

    if arguments.command == "seed-materials":
        return asyncio.run(seed_materials())

    # Unreachable: argparse rejects unknown commands. Present so main is total.
    return 1  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
