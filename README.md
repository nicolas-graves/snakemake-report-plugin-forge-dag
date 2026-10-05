# snakemake-report-plugin-forge-dag

A Snakemake report plugin that draws the job DAG, like `snakemake --dag`, with
every node linked to the line defining its rule on the git forge hosting it.
Rendered to SVG, the graph becomes a clickable index of the workflow's code.

```sh
snakemake TARGETS --forceall --reporter forge-dag \
    --report-forge-dag-path dag.svg
```

## Where links point

Snakemake itself says where each rule is defined (its Snakefile and line), so
rules from the main Snakefile, from `include:`d files and from `module`s are
all located the same way, without parsing. Each file is then linked inside the
git repository that holds it:

- **The workflow's own repository** (the one holding the working directory):
  at its `HEAD`, on the forge named by its `origin` remote.
- **A git submodule** (typically a Snakemake `module` kept in its own
  repository): at the commit its superproject records for it (the gitlink in
  the superproject's `HEAD`, not whatever is checked out), on the forge named
  by the submodule's own `origin` remote.

Remotes are normalized to HTTPS (`git@host:g/p.git`, `ssh://git@host/g/p.git`
and `https://host/g/p.git` all become `https://host/g/p`). Links use GitHub's
`/blob/` form for `github.com` and GitLab's `/-/blob/` form otherwise.

A rule whose file lies outside git, in a repository without an `origin`
remote, or in a submodule its superproject does not record, is drawn without a
link and listed in a warning.

## Settings

| Option | Default | |
|---|---|---|
| `--report-forge-dag-path` | required | Output file. `.dot`/`.gv` writes DOT; any other suffix is rendered with graphviz (`dot -T<suffix>`), which must be on `PATH`. |
| `--report-forge-dag-base-url` | from `origin` | Forge web URL of the workflow's own repository, e.g. `https://gitlab.com/group/project`. |
| `--report-forge-dag-commit` | `HEAD` | Commit (or tag) to pin the workflow's own links to. |

## Notes

- The graph has the same nodes, labels, colors and edges as `--dag` for the
  same targets and flags. Nodes carry `URL`, `target="_blank"` and a
  `tooltip` with the file path and line.
- A report run builds the DAG like `--report` does: it fails on incomplete
  output files unless `--rerun-incomplete` is given, and logs a warning for
  each output without Snakemake metadata. It takes no lock.
- `RuleInterface.lineno` is a line of the compiled Snakefile. The plugin maps
  it back to the source line through `rule.workflow.linemaps`, and reads
  `job.wildcards`, `dag.needrun` and `dag.rules` for labels, styles and
  colors. These are Snakemake attributes outside the report plugin interface.
- graphviz 14 has been seen to drop edges or abort (`cannot allocate ps`) on
  these graphs, even tiny ones; graphviz 7.0.1 renders them reliably.

## Tests

```sh
guix shell snakemake python-pytest git graphviz@7.0.1 -- pytest
```

The tests build a real workflow in a temporary git repository with a module in
a submodule, and run Snakemake on it.

## License

GPL-3.0-or-later.
