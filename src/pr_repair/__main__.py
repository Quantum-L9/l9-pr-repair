"""Module entry point: ``python -m pr_repair`` == the ``pr-repair`` console script.

Both dispatch to :func:`pr_repair.cli.main`, so behaviour is identical. This
exists so callers that already have the package importable -- CI, which installs
only the locked dependencies and puts ``src`` on the path -- can invoke the CLI
without first building and installing the project. Installing it merely to reach
an entry point meant CI had to run a source build on every job.
"""

from __future__ import annotations

from pr_repair.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
