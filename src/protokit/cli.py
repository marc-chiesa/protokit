"""protokit — top-level CLI.

Click group that hosts the toolkit's subcommands. Each subcommand is
defined in its own subpackage so that ``protokit diff`` and
``protokit compat`` stay independently testable and importable.

Usage:
    protokit diff   ...  # message comparison
    protokit compat ...  # schema compatibility check
"""

from __future__ import annotations

import click

from protokit.message.cli import main as _diff_command
from protokit.schema.cli import main as _compat_command


@click.group()
@click.version_option(package_name="protokit")
def main() -> None:
    """Protocol Buffers toolkit: message diffing and schema compatibility."""


main.add_command(_diff_command, name="diff")
main.add_command(_compat_command, name="compat")
