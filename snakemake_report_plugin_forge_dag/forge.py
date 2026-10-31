"""Resolve a rule's source location to a forge permalink.

A location is a file and a 1-based line. The file belongs to some git
repository: either the workflow's own repository (the *root*), or a repository
nested in it as a git submodule. Each repository is linked on its own forge,
pinned to a commit:

- the root at ``commit`` (default: its ``HEAD``) under ``base_url`` (default:
  its ``origin`` remote);
- a submodule at the commit its superproject records for it (the gitlink in
  the superproject's ``HEAD``, not whatever happens to be checked out), under
  its own ``origin`` remote.

Only ``git`` is consulted, so this works for any workflow layout; there is no
knowledge of Snakemake ``module`` blocks.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Link:
    url: str
    tooltip: str  # "<path relative to the root repository>:<line>"


def normalize_remote(url: str) -> Optional[str]:
    """Turn a git remote URL into an HTTPS web base (no trailing ``.git``/``/``)."""
    url = url.strip()
    for pattern in (
        r"^git@([^:]+):(.+)$",
        r"^ssh://git@([^/]+)/(.+)$",
        r"^https?://([^/]+)/(.+)$",
    ):
        m = re.match(pattern, url)
        if m:
            host, path = m.group(1), m.group(2)
            break
    else:
        return None
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return f"https://{host}/{path}"


def blob_url(https_base: str, sha: str, rel: str, line: int) -> str:
    """Build a forge permalink for a file at a given commit."""
    host = https_base.split("/", 3)[2]
    if "github.com" in host:
        return f"{https_base}/blob/{sha}/{rel}#L{line}"
    # Default to GitLab-style permalinks (gitlab.com and self-hosted GitLab).
    return f"{https_base}/-/blob/{sha}/{rel}#L{line}"


def git(cwd: Path, *args: str) -> Optional[str]:
    """Run git in ``cwd``; return its stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True
        )
    except FileNotFoundError:  # git itself is missing
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


class ForgeLinkResolver:
    """Map (file, line) to forge permalinks, caching per-repository lookups.

    ``root`` is any path inside the workflow's repository. ``base_url`` and
    ``commit`` override what is derived from that repository's ``origin``
    remote and ``HEAD``.
    """

    def __init__(
        self,
        root: Path,
        base_url: Optional[str] = None,
        commit: Optional[str] = None,
    ):
        toplevel = git(root, "rev-parse", "--show-toplevel")
        if toplevel is None:
            raise ValueError(f"{root} is not inside a git repository")
        self.root = Path(toplevel).resolve()
        if base_url is None:
            remote = git(self.root, "remote", "get-url", "origin")
            base_url = normalize_remote(remote) if remote else None
        self._root_base = base_url.rstrip("/") if base_url else None
        self._root_commit = commit or git(self.root, "rev-parse", "HEAD")
        self._toplevel = cache(self._toplevel_uncached)
        self._base_and_sha = cache(self._base_and_sha_uncached)

    def _toplevel_uncached(self, directory: Path) -> Optional[Path]:
        toplevel = git(directory, "rev-parse", "--show-toplevel")
        return Path(toplevel).resolve() if toplevel else None

    def _base_and_sha_uncached(self, repo: Path):
        """Forge base and pinned commit of the repository at ``repo``."""
        if repo == self.root:
            return self._root_base, self._root_commit
        remote = git(repo, "remote", "get-url", "origin")
        base = normalize_remote(remote) if remote else None
        superproject = git(repo, "rev-parse", "--show-superproject-working-tree")
        if not superproject:
            return base, None
        superproject_path = Path(superproject).resolve()
        rel = os.path.relpath(repo, superproject_path)
        sha = git(superproject_path, "rev-parse", f"HEAD:{rel}")
        return base, sha

    def in_own_repo(self, file: Path) -> bool:
        """Whether ``file`` belongs to the workflow's own repository (not a submodule)."""
        return self._toplevel(Path(file).resolve().parent) == self.root

    def link(self, file: Path, line: int) -> Optional[Link]:
        """Permalink to ``file`` at ``line``, or None if it cannot be resolved
        (file outside any git repository, repository without ``origin``,
        submodule not recorded in its superproject's ``HEAD``)."""
        file = Path(file).resolve()
        repo = self._toplevel(file.parent)
        if repo is None:
            return None
        base, sha = self._base_and_sha(repo)
        if base is None or sha is None:
            return None
        url = blob_url(base, sha, file.relative_to(repo).as_posix(), line)
        try:
            shown = file.relative_to(self.root).as_posix()
        except ValueError:
            shown = file.as_posix()
        return Link(url=url, tooltip=f"{shown}:{line}")
