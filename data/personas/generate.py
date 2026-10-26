"""Generates the three synthetic persona portfolios and the dev retrieval labels.

Each persona gets a PDF CV, ~20 Markdown case studies, repositories (vague
README + code that reveals the real stack), client reviews and 150 past
proposals with outcomes. Case studies name only some skills and imply the rest,
so retrieval has to infer them. The true project skills are written to
evals/datasets/ (never into the corpus).

Run: uv run python -m data.personas.generate
"""

import json
import math
import random
import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from fpdf import FPDF

from gigsim import seed

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "personas"
DATASETS = ROOT / "evals" / "datasets"

PERSONAS = {"fr_ml": "ml", "fr_fs": "fullstack", "fr_da": "data"}
INDUSTRIES = ["fintech", "healthcare", "e-commerce", "logistics", "education", "real estate",
              "media", "legal", "travel", "manufacturing"]

# skill -> (phrase implying the skill without naming it, code file, code line)
HINTS = {
    "Python": ("wrote the core services as small, typed and tested scripts", "app.py",
               "def main() -> None:"),
    "PyTorch": ("trained a custom neural network on GPU tensors", "train.py",
                "import torch\nfrom torch import nn"),
    "LangChain": (("chained prompts, retrievers and output parsers with an LLM orchestration "
                  "library"), "app.py", "from langchain_core.prompts import ChatPromptTemplate"),
    "LangGraph": (("modelled the agent as a stateful graph with checkpoints and human approval "
                  "steps"), "agent.py", "from langgraph.graph import StateGraph"),
    "RAG": ("grounded every answer in passages retrieved from the client's own documents",
            "agent.py", "def retrieve_then_generate(question, store, llm):"),
    "Hugging Face": ("fine-tuned an open pretrained transformer checkpoint", "train.py",
                     "from transformers import AutoModelForSequenceClassification"),
    "scikit-learn": ("built a cross-validated gradient-boosted baseline with feature pipelines",
                     "train.py", "from sklearn.pipeline import Pipeline"),
    "Pinecone": ("stored the embeddings in a managed serverless vector index", "app.py",
                 "from pinecone import Pinecone"),
    "FastAPI": ("exposed it through an async Python web API with typed request schemas",
                "app.py", "from fastapi import FastAPI"),
    "Docker": ("shipped everything as container images so staging matched production",
               "Dockerfile", "FROM python:3.12-slim"),
    "MLOps": ("set up experiment tracking, a model registry and automated retraining",
              "train.py", "import mlflow"),
    "OpenAI API": ("called a hosted GPT model with function calling", "app.py",
                   "from openai import OpenAI"),
    "React": ("built the interface from reusable components and hooks", "App.tsx",
              "import { useState } from 'react';"),
    "Next.js": ("used server-side rendering and file-based routing for fast first loads",
                "page.tsx", "import Link from 'next/link';"),
    "TypeScript": ("typed the frontend and API contracts end to end", "App.tsx",
                   "type Props = { id: string };"),
    "Node.js": ("wrote the backend on a JavaScript server runtime", "server.ts",
                "import express from 'express';"),
    "PostgreSQL": ("modelled the data relationally with migrations and indexes", "schema.sql",
                   "CREATE INDEX idx_orders_user ON orders(user_id);"),
    "Django": ("used a batteries-included Python web framework with its admin and ORM",
               "models.py", "from django.db import models"),
    "Tailwind CSS": ("styled pages with utility classes instead of custom stylesheets",
                     "App.tsx", '<div className="flex gap-4 p-6">'),
    "AWS": ("deployed on Amazon cloud services with infrastructure as code", "deploy.py",
            "import boto3"),
    "Celery": ("moved slow work into a distributed background task queue with retries",
               "tasks.py", "from celery import Celery"),
    "Redis": ("put an in-memory cache and rate limiter in front of the database", "tasks.py",
              "import redis"),
    "Stripe": ("integrated subscription billing, webhooks and invoices with a payments provider",
               "billing.py", "import stripe"),
    "SQL": ("computed cohorts with window functions directly in the warehouse", "models.sql",
            "SELECT user_id, SUM(amount) OVER (PARTITION BY user_id) FROM orders;"),
    "dbt": ("built a tested, documented transformation layer with lineage between models",
            "models.sql", "{{ config(materialized='table') }}"),
    "pandas": ("cleaned and reshaped the raw exports with dataframes", "clean.py",
               "import pandas as pd"),
    "Power BI": ("delivered interactive reports with DAX measures for the finance team",
                 None, None),
    "Tableau": ("published drag-and-drop visual workbooks for executives", None, None),
    "Excel": ("automated the spreadsheet workflow with pivot tables and macros", None, None),
    "Snowflake": (("loaded everything into a cloud data warehouse with separate compute "
                  "clusters"), "models.sql", "USE WAREHOUSE analytics_wh;"),
    "BigQuery": ("queried billions of rows in Google's serverless warehouse", "clean.py",
                 "from google.cloud import bigquery"),
    "Looker": ("defined a semantic layer of reusable metrics for self-serve dashboards",
               "orders.lkml", "explore: orders {}"),
    "Airflow": ("scheduled the pipeline as DAGs with retries and alerts", "pipeline.py",
                "from airflow import DAG"),
    "Statistics": ("ran significance tests and confidence intervals on the experiment results",
                   "analysis.py", "from scipy import stats"),
}
GENERIC_OPENINGS = ["Dear Sir/Madam, I am an expert with many years of experience.",
                    "Hello, I have read your job post and I can do this job perfectly.",
                    "Hi, I am the best fit for your project. Please check my profile."]
REVIEW_LINES = ["Delivered ahead of schedule and explained every decision.",
                "Communicated clearly and handled scope changes calmly.",
                "Solid work, though the first milestone slipped by a few days.",
                "Would hire again. The handover documentation was excellent."]


def _project(rng: random.Random, fid: str, n: int, category: str) -> dict:
    vocab = seed.CATEGORIES[category]["skills"]
    title = rng.choice(seed.CATEGORIES[category]["titles"])
    skills = rng.sample(vocab, k=rng.randint(3, 5))
    skills += [s for s in seed.mentioned_skills(title, vocab) if s not in skills]
    named = rng.sample(skills, k=max(1, round(len(skills) * 0.6)))
    industry = rng.choice(INDUSTRIES)
    return {
        "id": f"{fid}-p{n:02d}", "persona": fid, "industry": industry,
        "title": f"{title} ({industry})",
        "date": (date(2022, 1, 1) + timedelta(days=rng.randint(0, 1700))).isoformat(),
        "skills": skills, "named": named,
        "metric": rng.choice(["cut processing time by {}%", "raised conversion by {}%",
                              "reduced cloud costs by {}%", "saved the team {} hours a week"]
                             ).format(rng.randint(12, 60)),
        "has_repo": rng.random() < 0.55,
    }


def _case_study(p: dict) -> str:
    implied = [HINTS[s][0] for s in p["skills"] if s not in p["named"]]
    approach = " ".join(f"I {h}." for h in implied)
    return (f"# {p['title']}\n\nClient industry: {p['industry']}  \nCompleted: {p['date']}\n\n"
            f"## Brief\n{p['title'].split(' (')[0]}.\n\n"
            f"## Approach\nMain stack: {', '.join(p['named'])}. {approach}\n\n"
            f"## Outcome\nThe delivered system {p['metric']}.\n")


def _repo(p: dict) -> dict[str, str]:
    files: dict[str, list[str]] = defaultdict(list)
    for s in p["skills"]:
        _, name, line = HINTS[s]
        if name:
            files[name].append(line)
    readme = (f"# {p['id']}\n\nInternal tool built for a {p['industry']} client. "
              "Run `make dev` to start it locally. See the docs folder for details.\n")
    return {"README.md": readme, **{n: "\n".join(lines) + "\n" for n, lines in files.items()}}


def _proposal(rng: random.Random, i: int, fid: str, category: str, projects: list[dict]) -> dict:
    job_skills = set(rng.sample(seed.CATEGORIES[category]["skills"], k=3))
    cited = max(projects, key=lambda p: len(job_skills & set(p["skills"])) + rng.random())
    overlap = len(job_skills & set(cited["skills"]))
    generic = rng.random() < 0.35
    opening = (rng.choice(GENERIC_OPENINGS) if generic else
               f"You need {', '.join(sorted(job_skills))}; I shipped exactly that for a "
               f"{cited['industry']} client.")
    body = f"In '{cited['title']}' I {HINTS[cited['named'][0]][0]} and {cited['metric']}."
    score = overlap * 0.25 - (0.35 if generic else 0) + rng.uniform(-0.2, 0.2)
    outcome = "won" if score > 0.75 else "replied" if score > 0.45 else "ignored"
    return {"id": f"{fid}-prop{i:03d}", "persona": fid, "project": cited["id"],
            "job_title": rng.choice(seed.CATEGORIES[category]["titles"]),
            "date": (date(2023, 1, 1) + timedelta(days=rng.randint(0, 1000))).isoformat(),
            "outcome": outcome, "text": f"{opening} {body} Happy to start this week."}


def _cv(path: Path, fid: str, projects: list[dict]) -> None:
    me = seed.FREELANCERS[fid]
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"{me['name']} - {me['title']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    skills = sorted({s for p in projects for s in p["named"]})
    experience = "\n".join(f"{p['date'][:4]}: {p['title']} - {p['metric']}."
                           for p in sorted(projects, key=lambda p: p["date"], reverse=True))
    pdf.multi_cell(0, 5, f"Freelance {me['title'].lower()} with {len(projects)} delivered "
                         f"client projects.\nSkills: {', '.join(skills)}\n\nExperience:\n"
                         f"{experience}\n\nEducation: BSc Computer Science.")
    pdf.output(str(path))


def generate(seed_value: int = 7) -> None:
    rng = random.Random(seed_value)
    truth, dev = {}, []
    jobs = [j for j in seed.build()["jobs"].values() if not j["_truth"]["duplicate_of"]]
    for fid, category in PERSONAS.items():
        root = OUT / fid
        shutil.rmtree(root, ignore_errors=True)
        (root / "case_studies").mkdir(parents=True)
        projects = [_project(rng, fid, n, category) for n in range(1, 21)]
        for p in projects:
            truth[p["id"]] = {"persona": fid, "skills": p["skills"], "named": p["named"]}
            (root / "case_studies" / f"{p['id']}.md").write_text(_case_study(p), encoding="utf-8")
            if p["has_repo"]:
                for name, text in _repo(p).items():
                    path = root / "repos" / p["id"] / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
        reviews = [{"id": f"{p['id']}-review", "persona": fid, "project": p["id"],
                    "date": p["date"], "rating": rng.choice([4, 4.5, 5]),
                    "text": f"{rng.choice(REVIEW_LINES)} They {HINTS[rng.choice(p['skills'])][0]}."}
                   for p in projects if rng.random() < 0.6]
        proposals = [_proposal(rng, i, fid, category, projects) for i in range(1, 151)]
        for name, rows in (("reviews.jsonl", reviews), ("proposals.jsonl", proposals)):
            (root / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        _cv(root / "cv.pdf", fid, projects)

        # Dev retrieval labels: first 200 in-category jobs (the rest stay held out).
        for job in [j for j in jobs if j["_truth"]["category"] == category][:200]:
            need = set(job["skills"])
            gains = {p["id"]: len(need & set(p["skills"])) for p in projects}
            enough = max(2, math.ceil(0.6 * len(need)))  # covers most of the job's stack
            relevant = {pid: g for pid, g in gains.items() if g >= enough}
            if relevant:
                dev.append({"persona": fid, "job_id": job["id"], "skills": job["skills"],
                            "query": f"{job['title']}\n\n{job['description']}",
                            "relevant": relevant})
    DATASETS.mkdir(parents=True, exist_ok=True)
    (DATASETS / "persona_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    (DATASETS / "dev_retrieval.jsonl").write_text("".join(json.dumps(r) + "\n" for r in dev),
                                                  encoding="utf-8")
    print(f"{len(truth)} projects, {len(dev)} dev retrieval queries")


if __name__ == "__main__":
    generate()
