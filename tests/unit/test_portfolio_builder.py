import os
from typing import Any

import pytest
from mcp.server import MCPServer

from agent.config import load_config
from agent.handoffs import RepoCaseStudy
from agent.mcp_client import Toolbox
from rag import portfolio_builder as pb
from rag.ingest.loaders import load_persona
from rag.retriever import PERSONAS_DIR

REPO = {"README.md": "# demo\n\nInternal tool for a logistics client. Uses Celery, they say.\n",
        "tasks.py": "from celery import Celery\nimport redis\n",
        "page.tsx": "import Link from 'next/link';\n"}


def test_detector_trusts_code_not_the_readme():
    found = pb.detect({"README.md": "Built with Django and Stripe."} | REPO)
    assert {"Celery", "Redis", "Next.js", "TypeScript"} <= found.keys()
    assert "Django" not in found and "Stripe" not in found  # only named in prose
    assert found["Celery"] == "tasks.py: from celery import Celery"


def test_verification_drops_sentences_naming_skills_without_code():
    raw = RepoCaseStudy(title="Queue", skills=["Celery", "Kubernetes", "Django"],
                        summary="Background jobs run on Celery. The admin is built with Django.")
    study, dropped = pb.verify(raw, {"Celery": "tasks.py: from celery import Celery"})
    assert study.summary == "Background jobs run on Celery."
    assert dropped == ["The admin is built with Django."]
    assert study.skills == ["Celery"]


def test_file_names_are_not_skill_claims():
    raw = RepoCaseStudy(title="Warehouse", skills=["Snowflake"],
                        summary="Snowflake runs the warehouse, set in models.sql.")
    study, dropped = pb.verify(raw, {"Snowflake": "models.sql: USE WAREHOUSE analytics_wh;"})
    assert dropped == [] and study.summary == raw.summary  # ".sql" is not the skill SQL


def _fake_github(files: dict[str, str]) -> MCPServer:
    """The structured content GitHub's get_file_contents returns (checked against the live
    server): a list of entries for a folder; for a file, a status message plus the file as
    a resource block."""
    server = MCPServer("fake-github")

    @server.tool()
    async def get_file_contents(owner: str, repo: str, path: str,
                                ref: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
        if path in files:
            return {"content": [
                {"type": "text", "text": "successfully downloaded text file (SHA: 0)"},
                {"type": "resource", "resource": {
                    "uri": f"repo://{owner}/{repo}/contents/{path}",
                    "mimeType": "text/plain; charset=utf-8", "text": files[path]}}]}
        children = {p[len(path) + 1:].split("/")[0] for p in files if p.startswith(path + "/")}
        return [{"type": "file" if f"{path}/{c}" in files else "dir", "name": c,
                 "path": f"{path}/{c}"} for c in sorted(children)]
    return server


async def test_github_source_reads_repositories_through_mcp():
    files = {f"repos/fr_x/fr_x-p01/{name}": text for name, text in REPO.items()}
    source = pb.GitHubRepos(Toolbox({"github": _fake_github(files)}), "acme", "portfolio",
                            "main", "repos/{persona}")
    repos = await source.repos("fr_x")
    url, got = repos["fr_x-p01"]
    assert got == REPO
    assert url == "https://github.com/acme/portfolio/tree/main/repos/fr_x/fr_x-p01"


async def test_build_writes_case_studies_the_index_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "VERIFIED_DIR", tmp_path)
    manifest = await pb.build("fr_ml", pb.LocalRepos(), use_llm=False)
    assert manifest and all(m["dropped_sentences"] == [] for m in manifest.values())
    docs = load_persona(PERSONAS_DIR / "fr_ml", tmp_path / "fr_ml")
    verified = [d for d in docs if d.type == "verified_case_study"]
    assert {d.project for d in verified} == set(manifest)
    assert "## Code-verified stack" in verified[0].text


@pytest.mark.live
async def test_github_mcp_server_live():
    load_config()  # loads .env
    if not os.getenv("GITHUB_TOKEN"):
        pytest.skip("GITHUB_TOKEN not set")
    repos = await pb.GitHubRepos.from_config().repos("fr_ml")
    assert "fr_ml-p01" in repos and "README.md" in repos["fr_ml-p01"][1]
