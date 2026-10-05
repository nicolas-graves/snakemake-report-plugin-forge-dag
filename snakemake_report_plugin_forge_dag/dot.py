"""Draw the job DAG as DOT, in the style of ``snakemake --dag``.

The graph comes from the report interface (``dag.dependencies``, ``job.rule``).
Four things it does not expose are read from Snakemake objects directly, each
optional or failing loudly:

- ``rule.workflow.linemaps``: ``RuleInterface.lineno`` is a line of the
  *compiled* Snakefile; this map translates it back to the source line;
- ``job.wildcards``: the wildcard lines of a node's label;
- ``dag.needrun(job)``: dashed outline for jobs that would not run;
- ``dag.rules``: all workflow rules, over which hues are spread as --dag does,
  so a rule keeps its color across graphs of different targets.
"""

from __future__ import annotations

from typing import Callable, Optional

from snakemake_interface_common.exceptions import WorkflowError

from snakemake_report_plugin_forge_dag.forge import Link


def rule_source_line(rule) -> int:
    """1-based line of the ``rule``/``checkpoint`` statement in rule.snakefile."""
    linemaps = getattr(getattr(rule, "workflow", None), "linemaps", None)
    try:
        return linemaps[rule.snakefile][rule.lineno]
    except (TypeError, KeyError) as e:
        raise WorkflowError(
            f"forge-dag: no source line map for rule {rule.name} "
            f"({rule.snakefile}, compiled line {rule.lineno})",
            e,
        )


def _quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _new_wildcards(job, deps) -> list[str]:
    """Wildcards a job introduces relative to its dependencies, as --dag shows."""
    wildcards = getattr(job, "wildcards", None)
    if wildcards is None:
        return []
    new = set(wildcards.items())
    for dep in deps:
        new.difference_update(getattr(dep, "wildcards", {}).items())
    return sorted(f"{name}: {value}" for name, value in new)


def render_dot(dag, link: Callable[[object], Optional[Link]]) -> str:
    """DOT text of ``dag``; ``link(rule)`` gives each node's URL, if any."""
    dependencies = dag.dependencies
    jobs = list(dependencies.keys())
    ids = {job: i for i, job in enumerate(jobs)}

    rule_names = sorted(
        {rule.name for rule in getattr(dag, "rules", ())}
        | {job.rule.name for job in jobs}
    )
    huefactor = 2 / (3 * len(rule_names)) if rule_names else 0
    color = {name: f"{i * huefactor:.2f} 0.6 0.85" for i, name in enumerate(rule_names)}
    needrun = getattr(dag, "needrun", lambda job: True)

    links: dict[str, Optional[Link]] = {}
    lines = []
    for job in jobs:
        rule = job.rule
        if rule.name not in links:
            links[rule.name] = link(rule)
        deps = dependencies[job]
        label = "\\n".join(
            _quote(part) for part in [rule.name, *_new_wildcards(job, deps)]
        )
        style = "rounded" if needrun(job) else "rounded,dashed"
        attrs = f'label = "{label}", color = "{color[rule.name]}", style="{style}"'
        found = links[rule.name]
        if found is not None:
            attrs += (
                f', URL="{_quote(found.url)}", target="_blank", '
                f'tooltip="{_quote(found.tooltip)}"'
            )
        lines.append(f"\t{ids[job]}[{attrs}];")
    for job in jobs:
        for dep in dependencies[job]:
            lines.append(f"\t{ids[dep]} -> {ids[job]}")

    return (
        "digraph snakemake_dag {\n"
        "    graph[bgcolor=white, margin=0];\n"
        "    node[shape=box, style=rounded, fontname=sans, fontsize=10, penwidth=2];\n"
        "    edge[penwidth=2, color=grey];\n"
        + "".join(f"{line}\n" for line in lines)
        + "}\n"
    )
