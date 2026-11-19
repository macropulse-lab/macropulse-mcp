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

    assert sorted(publish["needs"]) == ["build", "test"]
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


def _runs(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job.get("steps", []) if "run" in step]


def _uploads_dist(job: dict[str, Any]) -> bool:
    return any(
        step.get("uses", "").startswith("actions/upload-artifact@")
        and str(step.get("with", {}).get("path", "")).startswith("dist")
        for step in job.get("steps", [])
    )


def test_the_job_that_uploads_dist_installs_only_hash_pinned_wheels() -> None:
    jobs = _load("release.yml")["jobs"]
    uploaders = {name: job for name, job in jobs.items() if _uploads_dist(job)}

    assert set(uploaders) == {"build"}
    for name, job in uploaders.items():
        for run in _runs(job):
            for line in run.splitlines():
                if "pip install" in line:
                    assert "--require-hashes" in line, f"{name}: {line}"
                    assert "--only-binary=:all:" in line, f"{name}: {line}"
                    assert " -e " not in line and "[dev]" not in line, f"{name}: {line}"
        assert not any(
            check in run
            for run in _runs(job)
            for check in ("pytest", "ruff", "black", "isort", "mypy")
        ), f"{name} must not run the test toolchain"


def test_build_job_checks_ancestry_and_versions_then_builds_and_uploads() -> None:
    build = _load("release.yml")["jobs"]["build"]
    runs = "\n".join(_runs(build))

    assert build["permissions"] == {"contents": "read"}
    assert build["steps"][0]["with"]["fetch-depth"] == 0
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/master' in runs
    assert "jq -e --arg v \"$VERSION\" '.version == $v and .packages[0].version == $v'" in runs
    assert "grep" not in runs
    order = [
        "pip install --require-hashes --only-binary=:all: -r .github/release/release-tools.txt",
        "python -m build --no-isolation",
        "twine check --strict",
    ]
    positions = [runs.index(item) for item in order]
    assert positions == sorted(positions)
    assert _uses(build)[-1].startswith("actions/upload-artifact@")


def test_test_job_runs_lint_types_and_tests_without_publishing_rights() -> None:
    jobs = _load("release.yml")["jobs"]
    test = jobs["test"]
    runs = "\n".join(_runs(test))

    assert test["permissions"] == {"contents": "read"}
    for check in ("ruff check", "black --check", "isort --check-only", "mypy src tests", "pytest"):
        assert check in runs, check
    assert not _uploads_dist(test)
    assert sorted(jobs["publish"]["needs"]) == ["build", "test"]


def test_release_tools_are_pinned_with_hashes() -> None:
    lock = (WORKFLOWS.parent / "release" / "release-tools.txt").read_text(encoding="utf-8")

    for tool in ("build==", "twine==", "hatchling=="):
        assert tool in lock, tool
    pins = re.findall(r"^[a-z0-9_.-]+==\S+", lock, flags=re.MULTILINE)
    assert pins and lock.count("--hash=sha256:") >= len(pins)
