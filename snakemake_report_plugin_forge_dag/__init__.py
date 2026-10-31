"""Snakemake report plugin: the job DAG, each node linked to its rule's source.

``snakemake TARGETS --reporter forge-dag --report-forge-dag-path dag.svg``
draws the same job graph as ``snakemake TARGETS --dag`` and gives every node a
graphviz ``URL`` pointing at the line defining its rule, on the forge hosting
the file (see :mod:`.forge`). Rules from ``include:``d files and from modules
kept in git submodules are located by Snakemake itself, not by parsing.
"""

# No `from __future__ import annotations`: Snakemake builds CLI options from
# the settings fields' runtime types.
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from snakemake_interface_common.exceptions import WorkflowError
from snakemake_interface_common.logging import get_logger
from snakemake_interface_report_plugins.reporter import ReporterBase
from snakemake_interface_report_plugins.settings import ReportSettingsBase

from snakemake_report_plugin_forge_dag.dot import render_dot, rule_source_line
from snakemake_report_plugin_forge_dag.forge import ForgeLinkResolver

__all__ = ["ReportSettings", "Reporter"]

DOT_SUFFIXES = {".dot", ".gv"}


@dataclass
class ReportSettings(ReportSettingsBase):
    path: Optional[Path] = field(
        default=None,
        metadata={
            "help": "Output file. A .dot or .gv suffix writes the DOT graph; any "
            "other suffix is rendered by graphviz (`dot -T<suffix>`, e.g. .svg), "
            "which must then be on PATH.",
            "env_var": False,
            "required": True,
        },
    )
    base_url: Optional[str] = field(
        default=None,
        metadata={
            "help": "Forge web URL of the workflow's own repository, e.g. "
            "https://gitlab.com/group/project (default: derived from its "
            "`origin` remote). Submodules always use their own `origin`.",
            "env_var": False,
            "required": False,
        },
    )
    unlink_own_repo: bool = field(
        default=False,
        metadata={
            "help": "Draw the rules of the workflow's own repository without "
            "links, e.g. when that repository is private. Submodule rules keep "
            "their links.",
            "env_var": False,
            "required": False,
        },
    )
    commit: Optional[str] = field(
        default=None,
        metadata={
            "help": "Commit to pin links into the workflow's own repository to "
            "(default: its HEAD). Submodules are pinned to the commit their "
            "superproject records.",
            "env_var": False,
            "required": False,
        },
    )


class Reporter(ReporterBase):
    def render(self):
        settings: ReportSettings = self.settings
        path = Path(settings.path)
        # The workflow's own repository is the one holding the working
        # directory, where Snakemake runs.
        resolver = ForgeLinkResolver(
            Path.cwd(), base_url=settings.base_url, commit=settings.commit
        )

        unresolved = set()

        def link(rule):
            if settings.unlink_own_repo and resolver.in_own_repo(Path(rule.snakefile)):
                return None
            line = rule_source_line(rule)
            found = resolver.link(Path(rule.snakefile), line)
            if found is None:
                unresolved.add(rule.name)
            return found

        dot = render_dot(self.dag, link)
        if unresolved:
            get_logger().warning(
                f"forge-dag: {len(unresolved)} rule(s) left unlinked (file "
                "outside git, repository without an `origin` remote, or "
                "submodule not recorded in its superproject's HEAD): "
                + ", ".join(sorted(unresolved))
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in DOT_SUFFIXES:
            path.write_text(dot, encoding="utf-8")
            return
        fmt = path.suffix.lstrip(".")
        if not fmt:
            raise WorkflowError(f"forge-dag: cannot infer a format from {path}")
        try:
            subprocess.run(
                ["dot", f"-T{fmt}", "-o", str(path)],
                input=dot,
                text=True,
                check=True,
            )
        except FileNotFoundError as e:
            raise WorkflowError(
                f"forge-dag: graphviz `dot` is needed to write {path}", e
            )
        except subprocess.CalledProcessError as e:
            raise WorkflowError(f"forge-dag: `dot -T{fmt}` failed", e)
