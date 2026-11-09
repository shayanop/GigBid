"""Portfolio builder (signature extension X3): turns code repositories into code-verified
case studies and adds them to the persona's evidence index.

1. Read each repository through GitHub's MCP server (or from disk with --source local).
2. Detect skills from the code itself: imports, file types and SQL markers. Every detected
   skill keeps the file and line that shows it.
3. Have a model write a short case study from the README and the detected skills, then drop
   any sentence that names a skill the code does not show (counted as caught hallucinations).
4. Write Markdown to data/verified_case_studies/<persona>/<project>.md. The index
   picks these up when rag.verified_case_studies is true.

Run: uv run python -m rag.portfolio_builder fr_ml fr_fs fr_da [--source local] [--no-llm]
"""

import argparse
import asyncio
import json
import os
import re
import sys

from agent.config import load_config
from agent.handoffs import RepoCaseStudy
from gigsim.seed import mentioned_skills
from rag.ingest.loaders import SKILLS
from rag.retriever import PERSONAS_DIR, VERIFIED_DIR

PY, JS = r"\.py$", r"\.(jsx?|tsx?|mjs)$"
# skill -> (file name pattern, line pattern). One matching line is code evidence for the skill.
# ponytail: import and file-type rules for the GigSim vocabulary; parse requirements.txt and
# package.json too for real repositories, where dependencies are declared, not just imported.
SIGNATURES: dict[str, tuple[str, str]] = {
    "Python": (PY, r"^\s*(def|class|import|from)\s"),
    "PyTorch": (PY, r"^\s*(import|from)\s+torch\b"),
    "LangChain": (PY, r"^\s*(import|from)\s+langchain"),
    "LangGraph": (PY, r"^\s*(import|from)\s+langgraph\b"),
    "RAG": (PY, r"retriev\w*.*(generat|llm)"),
    "Hugging Face": (PY, r"^\s*(import|from)\s+(transformers|datasets|huggingface_hub)\b"),
    "scikit-learn": (PY, r"^\s*(import|from)\s+sklearn\b"),
    "Pinecone": (PY, r"^\s*(import|from)\s+pinecone\b"),
    "FastAPI": (PY, r"^\s*(import|from)\s+fastapi\b"),
    "MLOps": (PY, r"^\s*(import|from)\s+(mlflow|wandb)\b"),
    "OpenAI API": (PY, r"^\s*(import|from)\s+openai\b"),
    "Django": (PY, r"^\s*(import|from)\s+django\b"),
    "AWS": (PY, r"^\s*(import|from)\s+(boto3|botocore)\b"),
    "Celery": (PY, r"^\s*(import|from)\s+celery\b"),
    "Redis": (PY, r"^\s*(import|from)\s+redis\b"),
    "Stripe": (PY, r"^\s*(import|from)\s+stripe\b"),
    "pandas": (PY, r"^\s*(import|from)\s+pandas\b"),
    "BigQuery": (PY, r"google\.cloud.*\bbigquery\b"),
    "Airflow": (PY, r"^\s*(import|from)\s+airflow\b"),
    "Statistics": (PY, r"^\s*(import|from)\s+(scipy|statsmodels)\b"),
    "Docker": (r"(^|/)(Dockerfile|docker-compose\.ya?ml)$", r"^\s*(FROM|services:)"),
    "React": (JS, r"""from\s+['"]react['"]"""),
    "Next.js": (JS, r"""from\s+['"]next/"""),
    "TypeScript": (r"\.tsx?$", r"\S"),
    "Node.js": (JS, r"""from\s+['"](express|fastify|koa)['"]|require\(['"]express['"]\)"""),
    "Tailwind CSS": (r"\.(jsx|tsx|html)$", r'class(Name)?="[^"]*\b(flex|grid|p-\d|gap-\d)\b'),
    "PostgreSQL": (r"\.sql$", r"\b(CREATE\s+(UNIQUE\s+)?INDEX|SERIAL|JSONB)\b"),
    "SQL": (r"\.sql$", r"^\s*(SELECT|WITH)\b"),
    "dbt": (r"\.sql$", r"\{\{\s*(config|ref|source)\s*\("),
    "Snowflake": (r"\.sql$", r"\bUSE\s+WAREHOUSE\b"),
    "Looker": (r"\.lkml$", r"\S"),
}


def detect(files: dict[str, str]) -> dict[str, str]:
    """Skill -> "path: line" for the first line of code that shows it."""
    found: dict[str, str] = {}
    for skill, (name, pattern) in SIGNATURES.items():
        for path, text in sorted(files.items()):
            if re.search(name, path):
                line = next((ln.strip() for ln in text.splitlines() if re.search(pattern, ln)),
                            None)
                if line:
                    found[skill] = f"{path}: {line}"
                    break
    return found


FILE_NAME = re.compile(r"[\w/-]+\.(py|sql|tsx?|lkml|md|ya?ml|json|txt|toml)\b")


def skills_named(text: str) -> list[str]:
    """Skills a text names, ignoring file names ("models.sql" does not claim SQL)."""
    return mentioned_skills(FILE_NAME.sub("", text), SKILLS)


def verify(study: RepoCaseStudy, detected: dict[str, str]) -> tuple[RepoCaseStudy, list[str]]:
    """Keeps only code-backed skills and drops summary sentences naming any other skill."""
    sentences = re.split(r"(?<=[.!?])\s+", study.summary.strip())
    dropped = [s for s in sentences if set(skills_named(s)) - detected.keys()]
    return study.model_copy(update={
        "summary": " ".join(s for s in sentences if s not in dropped),
        "skills": [s for s in study.skills if s in detected]}), dropped


def render(project: str, source: str, study: RepoCaseStudy, detected: dict[str, str]) -> str:
    stack = "\n".join(f"- {skill}: `{where}`" for skill, where in detected.items())
    return (f"# {study.title} (code-verified)\n\nProject: {project}  \nRepository: {source}\n\n"
            f"## Summary\n{study.summary}\n\n## Code-verified stack\n{stack}\n")


def template(files: dict[str, str], detected: dict[str, str]) -> RepoCaseStudy:
    """The no-model baseline: the README's first line and the detected stack."""
    readme = next((t for p, t in files.items() if p.lower().endswith("readme.md")), "")
    first = next((ln for ln in readme.splitlines()[1:] if ln.strip()), "").strip()
    return RepoCaseStudy(title=", ".join(list(detected)[:3]) or "Repository",
                         summary=first, skills=list(detected))


async def write(project: str, files: dict[str, str], detected: dict[str, str]) -> RepoCaseStudy:
    from agent.nodes import common
    readme = next((t for p, t in files.items() if p.lower().endswith("readme.md")), "none")
    stack = "\n".join(f"- {s} ({where})" for s, where in detected.items()) or "none"
    return await common.ask("portfolio_builder", RepoCaseStudy,
                            f"Repository {project}\n\n" + common.untrusted("readme", readme)
                            + f"\n\nSkills detected in the code:\n{stack}")


class LocalRepos:
    """The persona's repository folders on disk (offline runs and tests)."""

    async def repos(self, persona: str) -> dict[str, tuple[str, dict[str, str]]]:
        root = PERSONAS_DIR / persona / "repos"
        return {d.name: (d.relative_to(PERSONAS_DIR.parents[1]).as_posix(),
                         {f.name: f.read_text(encoding="utf-8") for f in d.iterdir() if f.is_file()})
                for d in sorted(root.iterdir()) if d.is_dir()}


class GitHubRepos:
    """Repositories read through GitHub's MCP server (get_file_contents)."""

    def __init__(self, toolbox, owner: str, repo: str, ref: str, repos_path: str):
        self.toolbox, self.owner, self.repo, self.ref = toolbox, owner, repo, ref
        self.repos_path = repos_path

    @classmethod
    def from_config(cls) -> "GitHubRepos":
        from agent.mcp_client import Toolbox
        cfg = load_config()["portfolio_builder"]
        toolbox = Toolbox({"github": cfg["github_mcp_url"]},
                          {"github": os.environ["GITHUB_TOKEN"].strip()})
        return cls(toolbox, cfg["owner"], cfg["repo"], cfg["ref"], cfg["repos_path"])

    async def _get(self, path: str):
        return await self.toolbox.call("portfolio_builder", "github", "get_file_contents", {
            "owner": self.owner, "repo": self.repo, "path": path, "ref": self.ref})

    async def _listing(self, path: str) -> list[dict]:
        entries = await self._get(path)  # a folder: one entry per file or subfolder
        if not isinstance(entries, list):
            raise TypeError(f"{path} is not a folder")
        return entries

    async def _text(self, path: str) -> str:
        # A file: {"content": [status message, the file as a resource block]}. GitHub sometimes
        # answers a file that exists with "Failed to get file contents" and no data; retry.
        for attempt in range(3):
            if data := await self._get(path):
                return next(b["resource"]["text"] for b in data["content"]
                            if b.get("type") == "resource")
            await asyncio.sleep(1 + attempt)
        raise FileNotFoundError(f"GitHub returned no content for {path}")

    async def repos(self, persona: str) -> dict[str, tuple[str, dict[str, str]]]:
        base = self.repos_path.format(persona=persona)
        out = {}
        for entry in await self._listing(base):
            if entry.get("type") != "dir":
                continue
            names = [f for f in await self._listing(entry["path"]) if f.get("type") == "file"]
            texts = await asyncio.gather(*(self._text(f["path"]) for f in names))
            files = {f["name"]: text for f, text in zip(names, texts, strict=True)}
            url = f"https://github.com/{self.owner}/{self.repo}/tree/{self.ref}/{entry['path']}"
            out[entry["name"]] = (url, files)
        return out


async def build(persona: str, source, use_llm: bool = True) -> dict:
    """Writes one verified case study per repository; returns the per-project manifest."""
    out_dir = VERIFIED_DIR / persona
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for project, (where, files) in (await source.repos(persona)).items():
        detected = detect(files)
        raw = await write(project, files, detected) if use_llm else template(files, detected)
        study, dropped = verify(raw, detected)
        (out_dir / f"{project}.md").write_text(render(project, where, study, detected),
                                               encoding="utf-8")
        manifest[project] = {"source": where, "detected": detected,
                             "model_skills": raw.skills, "dropped_sentences": dropped,
                             "mentioned_before": skills_named(raw.summary),
                             "mentioned_after": skills_named(study.summary)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("personas", nargs="+")
    parser.add_argument("--source", choices=["github", "local"], default="github")
    parser.add_argument("--no-llm", action="store_true", help="template text, no model calls")
    args = parser.parse_args()
    load_config()  # loads .env
    source = GitHubRepos.from_config() if args.source == "github" else LocalRepos()

    async def run():
        for persona in args.personas:
            manifest = await build(persona, source, not args.no_llm)
            dropped = sum(len(m["dropped_sentences"]) for m in manifest.values())
            print(f"{persona}: {len(manifest)} repositories, {dropped} unverified sentences dropped")
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(run(), loop_factory=loop)


if __name__ == "__main__":
    main()
