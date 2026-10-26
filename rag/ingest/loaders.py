"""Loads a persona folder (CV PDF, case studies, repos, reviews, proposals) into
Documents with metadata, and splits them into fixed-size chunks."""

import json
import re
from pathlib import Path

from pypdf import PdfReader

from gigsim.seed import CATEGORIES, mentioned_skills
from rag.schema import Chunk, Document

# ponytail: vocabulary = the GigSim skill set; swap for a real taxonomy for live users.
SKILLS = sorted({s for c in CATEGORIES.values() for s in c["skills"]})


def _field(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def load_persona(root: Path) -> list[Document]:
    persona, docs = root.name, []
    if (cv := root / "cv.pdf").exists():
        text = "\n".join(page.extract_text() for page in PdfReader(cv).pages)
        docs.append(Document(id=f"{persona}-cv", persona=persona, type="cv", source="cv.pdf",
                             text=text))
    for path in sorted((root / "case_studies").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        docs.append(Document(
            id=path.stem, persona=persona, type="case_study", project=path.stem, text=text,
            source=path.relative_to(root).as_posix(),
            date=_field(r"Completed:\s*(\d{4}-\d{2}-\d{2})", text),
            client_industry=_field(r"Client industry:\s*([^\n]+)", text)))
    for path in sorted((root / "repos").glob("*/*")):
        project, rel = path.parent.name, path.relative_to(root).as_posix()
        docs.append(Document(
            id=f"{project}/{path.name}", persona=persona, project=project, source=rel,
            type="repo_readme" if path.name.lower() == "readme.md" else "code",
            text=f"Repository {project}, file {path.name}:\n{path.read_text(encoding='utf-8')}"))
    for name, doc_type in (("reviews.jsonl", "review"), ("proposals.jsonl", "proposal")):
        if not (root / name).exists():
            continue
        for line in (root / name).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            text = (f"Proposal for '{row['job_title']}':\n{row['text']}"
                    if doc_type == "proposal" else row["text"])
            docs.append(Document(id=row["id"], persona=persona, type=doc_type, text=text,
                                 source=f"{name}#{row['id']}", project=row.get("project"),
                                 date=row.get("date"), outcome=row.get("outcome")))
    return docs


def fixed_chunks(doc: Document, size: int, overlap: int) -> list[Chunk]:
    step = size - overlap
    pieces = [doc.text[i:i + size] for i in range(0, max(len(doc.text) - overlap, 1), step)]
    return [Chunk(**doc.model_dump(exclude={"id", "text"}), id=f"{doc.id}#{n}", doc_id=doc.id,
                  text=piece, skills=mentioned_skills(piece, SKILLS))
            for n, piece in enumerate(pieces)]
