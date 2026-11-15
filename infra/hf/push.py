"""Upload GigBid to a Hugging Face Docker Space in one commit (one rebuild).

Only files git would track are sent (so .env, data/raw and data/processed never leave),
minus what the image does not need. infra/hf/Dockerfile and infra/hf/README.md become the
Space's root Dockerfile and card. Files deleted locally are deleted in the Space.

Log in first (`uv run hf auth login`, a write token), then:
    uv run python infra/hf/push.py <user>/<space>
"""

import subprocess
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

ROOT = Path(__file__).resolve().parents[2]
SKIP = ("evals/", "tests/", "docs/", ".github/", ".claude/","apps/web/tests/", "README.md", "Makefile",
        "render.yaml", "GigBid_Project_Specification.md")
RENAMED = {"Dockerfile": "infra/hf/Dockerfile", "README.md": "infra/hf/README.md"}


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if not f.startswith(SKIP) and (ROOT / f).is_file()]


def main() -> None:
    repo = sys.argv[1]
    api = HfApi()
    api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)
    local = {f: ROOT / f for f in files()} | {k: ROOT / v for k, v in RENAMED.items()}
    ops = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(v)) for k, v in local.items()]
    ops += [CommitOperationDelete(path_in_repo=f) for f in api.list_repo_files(
        repo, repo_type="space") if f not in local and f != ".gitattributes"]
    api.create_commit(repo, ops, repo_type="space", commit_message="Deploy GigBid")
    print(f"uploaded {len(local)} files; build log: https://huggingface.co/spaces/{repo}")


if __name__ == "__main__":
    main()
