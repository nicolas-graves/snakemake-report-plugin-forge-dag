import subprocess

import pytest

from snakemake_report_plugin_forge_dag.forge import (
    ForgeLinkResolver,
    blob_url,
    normalize_remote,
)


@pytest.mark.parametrize(
    "remote",
    [
        "git@gitlab.com:g/p.git",
        "ssh://git@gitlab.com/g/p.git",
        "https://gitlab.com/g/p.git",
        "https://gitlab.com/g/p/",
    ],
)
def test_normalize_remote(remote):
    assert normalize_remote(remote) == "https://gitlab.com/g/p"


def test_normalize_remote_rejects_local_paths():
    assert normalize_remote("/srv/git/p.git") is None


def test_blob_url_github_and_gitlab():
    assert (
        blob_url("https://github.com/o/r", "abc", "a/Snakefile", 3)
        == "https://github.com/o/r/blob/abc/a/Snakefile#L3"
    )
    assert (
        blob_url("https://gitlab.example.org/g/p", "abc", "Snakefile", 1)
        == "https://gitlab.example.org/g/p/-/blob/abc/Snakefile#L1"
    )


def test_file_outside_git_is_unresolved(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    resolver = ForgeLinkResolver(repo, base_url="https://gitlab.com/g/p", commit="c")
    outside = tmp_path / "elsewhere" / "Snakefile"
    outside.parent.mkdir()
    outside.write_text("")
    assert resolver.link(outside, 1) is None


def test_settings_override_root_base_and_commit(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    resolver = ForgeLinkResolver(
        tmp_path, base_url="https://github.com/o/r/", commit="deadbeef"
    )
    smk = tmp_path / "rules" / "a.smk"
    smk.parent.mkdir()
    smk.write_text("")
    link = resolver.link(smk, 7)
    assert link.url == "https://github.com/o/r/blob/deadbeef/rules/a.smk#L7"
    assert link.tooltip == "rules/a.smk:7"
