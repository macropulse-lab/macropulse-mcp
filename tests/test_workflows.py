"""Supply-chain rules for the GitHub workflows, so a later edit cannot quietly undo them."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
PYPI_ACTION = "pypa/gh-action-pypi-publish@"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return data


def _uses(job: dict[str, Any]) -> list[str]:
    return [step["uses"] for step in job.get("steps", []) if "uses" in step]


@pytest.mark.parametrize("name", ["ci.yml", "release.yml"])
def test_every_action_is_pinned_to_a_commit_sha(name: str) -> None:
    for job_name, job in _load(name)["jobs"].items():
        for uses in _uses(job):
            assert PINNED.match(uses), f"{name}:{job_name} uses unpinned {uses}"


def test_release_defaults_to_no_permissions() -> None:
    assert _load("release.yml")["permissions"] == {}


def test_only_publish_and_registry_jobs_get_an_oidc_token() -> None:
    jobs = _load("release.yml")["jobs"]

    with_token = {n for n, j in jobs.items() if j.get("permissions", {}).get("id-token")}

    assert with_token == {"publish", "mcp-registry"}
    assert "id-token" not in jobs["build"]["permissions"]


def test_publish_job_only_downloads_the_artifact_and_runs_the_pinned_action() -> None:
    publish = _load("release.yml")["jobs"]["publish"]

    assert publish["needs"] == "build"
    assert publish["environment"] == "pypi"
    assert publish["permissions"] == {"id-token": "write"}
    steps = publish["steps"]
    assert len(steps) == 2
    assert steps[0]["uses"].startswith("actions/download-artifact@")
    assert steps[1]["uses"].startswith(PYPI_ACTION)
    assert all("run" not in step for step in steps)


def test_pypi_action_appears_only_in_the_publish_job() -> None:
    for job_name, job in _load("release.yml")["jobs"].items():
        if job_name != "publish":
            assert not any(u.startswith(PYPI_ACTION) for u in _uses(job)), job_name


def test_registry_job_runs_after_publish_with_minimal_permissions() -> None:
    registry = _load("release.yml")["jobs"]["mcp-registry"]

    assert registry["needs"] == "publish"
    assert registry["permissions"] == {"contents": "read", "id-token": "write"}


def test_build_job_checks_ancestry_versions_and_quality_before_upload() -> None:
    build = _load("release.yml")["jobs"]["build"]
    runs = "\n".join(step.get("run", "") for step in build["steps"])

    checkout = build["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/master' in runs
    assert "--require-hashes -r .github/release/release-tools.txt" in runs
    assert "python -m build --no-isolation" in runs
    for check in ("twine check --strict", "ruff check", "black --check", "mypy src", "pytest"):
        assert check in runs, check
    assert _uses(build)[-1].startswith("actions/upload-artifact@")


def test_release_tools_are_pinned_with_hashes() -> None:
    lock = (WORKFLOWS.parent / "release" / "release-tools.txt").read_text(encoding="utf-8")

    for tool in ("build==", "twine==", "hatchling=="):
        assert tool in lock, tool
    pins = re.findall(r"^[a-z0-9_.-]+==\S+", lock, flags=re.MULTILINE)
    assert pins and lock.count("--hash=sha256:") >= len(pins)
