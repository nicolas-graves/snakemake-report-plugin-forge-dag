"""End-to-end: a real workflow in a git repository with a module in a submodule."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
}


def git(cwd, *args):
    result = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    )
    return result.stdout.strip()


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def line_of(path: Path, statement: str) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    return next(i for i, line in enumerate(lines, start=1) if line.startswith(statement))


# Directives spanning several lines before later rules, so that compiled and
# source line numbers diverge: links must carry the source ones.
MODULE_SNAKEFILE = """\
rule r:
    output:
        "m/{sample}.txt",
    params:
        x=1,
    shell:
        "touch {output}"
"""

ROOT_SNAKEFILE = """\
module m:
    snakefile:
        "modules/m/Snakefile"

use rule * from m as m_*

include: "sub/Snakefile"


rule top:
    input:
        "mid/a.txt",
    output:
        "top.txt",
    shell:
        "touch {output}"
"""

SUB_SNAKEFILE = """\
include: "nested.smk"


rule mid:
    input:
        "deep/{sample}.txt",
    output:
        "mid/{sample}.txt",
    shell:
        "touch {output}"
"""

NESTED_SMK = """\
def unused():
    return [
        1,
        2,
    ]


rule deep:
    input:
        "m/{sample}.txt",
    output:
        "deep/{sample}.txt",
    shell:
        "touch {output}"
"""


@pytest.fixture
def workflow(tmp_path):
    """Root repo (origin on GitLab) with `modules/m` as a submodule (on GitHub)
    whose checkout is one commit ahead of the gitlink the root records."""
    upstream = tmp_path / "upstream-m"
    git(tmp_path, "init", "-q", str(upstream))
    write(upstream / "Snakefile", MODULE_SNAKEFILE)
    git(upstream, "add", ".")
    git(upstream, "commit", "-qm", "m")

    root = tmp_path / "root"
    git(tmp_path, "init", "-q", str(root))
    git(root, "remote", "add", "origin", "git@gitlab.com:g/p.git")
    git(root, "submodule", "add", "-q", str(upstream), "modules/m")
    git(root / "modules" / "m", "remote", "set-url", "origin", "git@github.com:o/m.git")
    write(root / "Snakefile", ROOT_SNAKEFILE)
    write(root / "sub" / "Snakefile", SUB_SNAKEFILE)
    write(root / "sub" / "nested.smk", NESTED_SMK)
    git(root, "add", ".")
    git(root, "commit", "-qm", "root")
    recorded = git(root, "rev-parse", "HEAD:modules/m")

    # Move the submodule checkout past the recorded commit.
    write(root / "modules" / "m" / "README", "later\n")
    git(root / "modules" / "m", "add", ".")
    git(root / "modules" / "m", "commit", "-qm", "later")
    return root, recorded


def run_report(root: Path, out: Path, *extra: str):
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(PLUGIN_ROOT), *filter(None, [os.environ.get("PYTHONPATH")])]
        ),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "snakemake",
            "top.txt",
            "--forceall",
            "--reporter",
            "forge-dag",
            "--report-forge-dag-path",
            str(out),
            *extra,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result


def node_attrs(dot: str) -> dict[str, str]:
    """First label line (the rule name) -> the node's attribute text."""
    nodes = {}
    for m in re.finditer(r'^\t\d+\[label = "([^"\\]*)(?:\\n[^"]*)?"(.*)\];$', dot, re.M):
        nodes[m.group(1)] = m.group(2)
    return nodes


def test_links_root_included_and_module_rules(workflow, tmp_path):
    root, recorded = workflow
    out = tmp_path / "dag.dot"
    run_report(root, out)
    nodes = node_attrs(out.read_text())
    head = git(root, "rev-parse", "HEAD")
    gitlab = f"https://gitlab.com/g/p/-/blob/{head}"

    assert set(nodes) == {"top", "mid", "deep", "m_r"}
    expected = {
        "top": (f"{gitlab}/Snakefile", "Snakefile", line_of(root / "Snakefile", "rule top:")),
        "mid": (
            f"{gitlab}/sub/Snakefile",
            "sub/Snakefile",
            line_of(root / "sub" / "Snakefile", "rule mid:"),
        ),
        "deep": (
            f"{gitlab}/sub/nested.smk",
            "sub/nested.smk",
            line_of(root / "sub" / "nested.smk", "rule deep:"),
        ),
        # Pinned to the gitlink recorded in the root, not the checkout's HEAD.
        "m_r": (
            f"https://github.com/o/m/blob/{recorded}/Snakefile",
            "modules/m/Snakefile",
            1,
        ),
    }
    for rule, (url, shown, line) in expected.items():
        assert f'URL="{url}#L{line}"' in nodes[rule], rule
        assert f'tooltip="{shown}:{line}"' in nodes[rule], rule


def test_graph_matches_snakemake_dag(workflow, tmp_path):
    """Same nodes (labels, colors, styles) and edges as `snakemake --dag`."""
    root, _ = workflow
    out = tmp_path / "dag.dot"
    run_report(root, out)
    plain = subprocess.run(
        [sys.executable, "-m", "snakemake", "top.txt", "--forceall", "--dag"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    def graph(dot):
        node = re.compile(r'^\s*(\d+)\[(label = "(?:[^"\\]|\\.)*", color = "[^"]*", style="[^"]*")')
        ids = {m.group(1): m.group(2) for m in map(node.match, dot.splitlines()) if m}
        edges = {
            (ids[a], ids[b]) for a, b in re.findall(r"^\s*(\d+) -> (\d+)\s*$", dot, re.M)
        }
        return set(ids.values()), edges

    assert graph(out.read_text()) == graph(plain)
    # Wildcards show on the job introducing them, as with --dag.
    assert 'label = "m_r\\nsample: a"' in out.read_text()


def test_settings_override_root_forge(workflow, tmp_path):
    root, _ = workflow
    out = tmp_path / "dag.dot"
    run_report(
        root,
        out,
        "--report-forge-dag-base-url",
        "https://github.com/mirror/p",
        "--report-forge-dag-commit",
        "v1.0",
    )
    nodes = node_attrs(out.read_text())
    assert 'URL="https://github.com/mirror/p/blob/v1.0/Snakefile#L' in nodes["top"]
    assert "https://github.com/o/m/blob/" in nodes["m_r"]


def test_use_rule_with_links_to_its_use_statement(workflow, tmp_path):
    """A rule derived with `use rule ... with:` links to that statement."""
    root, _ = workflow
    text = ROOT_SNAKEFILE.replace('"mid/a.txt",', '"mid/a.txt",\n        "mid2/a.txt",') + """

use rule mid as mid2 with:
    output:
        "mid2/{sample}.txt",
"""
    write(root / "Snakefile", text)
    git(root, "commit", "-qam", "use rule")
    out = tmp_path / "dag.dot"
    run_report(root, out)
    nodes = node_attrs(out.read_text())
    head = git(root, "rev-parse", "HEAD")
    line = line_of(root / "Snakefile", "use rule mid as mid2")
    assert f'URL="https://gitlab.com/g/p/-/blob/{head}/Snakefile#L{line}"' in nodes["mid2"]


def test_unlink_own_repo_keeps_submodule_links(workflow, tmp_path):
    root, recorded = workflow
    out = tmp_path / "dag.dot"
    result = run_report(root, out, "--report-forge-dag-unlink-own-repo")
    nodes = node_attrs(out.read_text())
    for rule in ("top", "mid", "deep"):
        assert "URL=" not in nodes[rule], rule
    assert f'URL="https://github.com/o/m/blob/{recorded}/Snakefile#L1"' in nodes["m_r"]
    # Unlinked on request, not unresolved: no warning.
    assert "left unlinked" not in result.stderr


def test_submodule_without_origin_stays_unlinked(workflow, tmp_path):
    root, _ = workflow
    git(root / "modules" / "m", "remote", "remove", "origin")
    out = tmp_path / "dag.dot"
    result = run_report(root, out)
    nodes = node_attrs(out.read_text())
    assert "URL=" not in nodes["m_r"]
    assert "URL=" in nodes["top"]
    assert "m_r" in result.stderr


@pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz not installed")
def test_svg_output_keeps_links(workflow, tmp_path):
    root, _ = workflow
    out = tmp_path / "dag.svg"
    run_report(root, out)
    svg = out.read_text()
    assert svg.lstrip().startswith("<?xml")
    assert "https://gitlab.com/g/p/-/blob/" in svg
