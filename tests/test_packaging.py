"""Release metadata stays consistent: versions, registry manifest, README marker."""

from __future__ import annotations

import importlib.metadata
import json
import tomllib
from pathlib import Path
from typing import Any

import jsonschema

from macropulse_mcp import __version__

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_NAME = "io.github.macropulse-lab/macropulse-mcp"


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _server_json() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    return data


def test_versions_agree() -> None:
    # Single source: hatch reads the version from macropulse_mcp/__init__.py.
    project = _pyproject()
    assert "version" in project["project"]["dynamic"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/macropulse_mcp/__init__.py"
    version = importlib.metadata.version("macropulse-mcp")
    manifest = _server_json()

    assert version == __version__ == manifest["version"]
    assert [p["version"] for p in manifest["packages"]] == [version]


def test_server_json_is_valid_against_the_registry_schema() -> None:
    schema = json.loads(
        (ROOT / "tests" / "fixtures" / "server.schema.2025-12-11.json").read_text(encoding="utf-8")
    )
    manifest = _server_json()

    assert manifest["$schema"] == schema["$id"]
    jsonschema.validate(manifest, schema)


def test_server_json_points_at_this_pypi_package() -> None:
    manifest = _server_json()
    (package,) = manifest["packages"]

    assert manifest["name"] == REGISTRY_NAME
    assert package["registryType"] == "pypi"
    assert package["identifier"] == _pyproject()["project"]["name"] == "macropulse-mcp"
    assert package["transport"] == {"type": "stdio"}
    key_var = {v["name"]: v for v in package["environmentVariables"]}["MACROPULSE_API_KEY"]
    assert key_var["isSecret"] is True
    assert key_var["isRequired"] is False


def test_readme_carries_the_registry_ownership_marker() -> None:
    # The MCP Registry checks the PyPI README for this exact marker.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"mcp-name: {REGISTRY_NAME}" in readme


def test_readme_installs_what_actually_exists() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "uvx macropulse-mcp" in readme
    assert "chatgpt" not in readme.lower()
    assert "alpha" not in readme.lower()


def test_registry_namespace_matches_the_repository_owner() -> None:
    # The registry's GitHub OIDC login only grants io.github.<repository_owner>/*,
    # so the name must follow the org that owns the repo the release runs in.
    manifest = _server_json()
    owner = manifest["repository"]["url"].removeprefix("https://github.com/").split("/")[0]

    assert manifest["name"].startswith(f"io.github.{owner}/")
    assert _pyproject()["project"]["urls"]["Repository"] == manifest["repository"]["url"]


def test_readme_warns_that_the_base_url_receives_the_key() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "`MACROPULSE_API_BASE` receives your API key." in readme
    assert "only at hosts you trust" in readme
