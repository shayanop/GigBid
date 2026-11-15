"""Real-data layer: downloads the public Kaggle datasets GigBid uses and turns them into
GigSim jobs and clients, a real-job retrieval set, a scam-detection set and market-rate
statistics. Every derived record says which fields are real and which are synthetic.

Run: uv run python -m data.real.prepare          (downloads what is missing, then builds)

Raw files go to data/raw/kaggle/ and outputs to data/processed/real/; both are git-ignored
(size, and the scam set's license is unknown). evals/results/real_data_summary.json, which
holds only aggregates, is committed. See docs/DATA_CARD.md.
"""

import csv
import hashlib
import html
import json
import math
import random
import re
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.redact import redact
from gigsim import seed
from gigsim.seed import CATEGORIES, mentioned_skills

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "kaggle"
OUT = ROOT / "data" / "processed" / "real"
TRUTH = ROOT / "evals" / "datasets" / "persona_truth.json"
SUMMARY = ROOT / "evals" / "results" / "real_data_summary.json"
csv.field_size_limit(2**31 - 1)

# folder -> (Kaggle ref, files, license, what GigBid uses it for)
SOURCES = {
    "upwork-60k": ("ahmedmyalo/upwork-freelance-jobs-60k", ["Final_Upwork_Dataset.csv"],
                   "Apache 2.0", "GigSim real-mode jobs and client histories"),
    "upwork-50k": ("asaniczka/upwork-job-postings-dataset-2024-50k-records", ["upwork-jobs.csv"],
                   "ODC-By 1.0", "real-job retrieval evaluation (held out from GigSim)"),
    "upwork-200k": ("asaniczka/all-jobs-on-upwork-200k-plus",
                    ["all_upwork_jobs_2024-02-07-2024-03-24.csv",
                     "all_upwork_jobs_2024-03-24-2024-05-21.csv",
                     "all_upwork_jobs_2024-05-21-2024-07-25.csv"],
                    "ODC-By 1.0", "posted budgets and hourly ranges (fair price bands)"),
    "contracts": ("asaniczka/freelance-contracts-dataset-1-3-million-entries", ["contracts.csv"],
                  "ODC-By 1.0", "amounts and hourly rates actually paid"),
    "freelancer-success": ("sarveshchhetri/freelancer-success-earnings-and-churn-prediction",
                           ["freelancer_gig_success_dataset.csv"], "Apache 2.0",
                           ("checked as a rate benchmark and rejected: synthetic, and its hourly "
                           "rates are clipped at 280 USD (the median for every skill)")),
    "fake-jobs": ("adityammantri/trial-1", ["processed_labeled_dataset_without_encoding.xlsx"],
                  "Unknown", "scam-detection evaluation of the Risk Assessor"),
}

# Upwork tags and title words that place a job in a persona's category. "other" otherwise.
CATEGORY_WORDS = {
    "ml": ["machine learning", "deep learning", "artificial intelligence", "neural network",
           "natural language processing", "computer vision", "tensorflow", "pytorch", "keras",
           "langchain", "langgraph", "large language model", "llm", "chatgpt", "openai",
           "generative ai", "hugging face", "scikit-learn", "chatbot", "mlops", "ai"],
    "fullstack": ["full stack", "full-stack", "react", "next.js", "node.js", "typescript",
                  "django", "fastapi", "vue.js", "angular", "web application", "saas",
                  "postgresql", "mern", "express", "laravel", "ruby on rails", "flask"],
    "data": ["data analysis", "data analytics", "data visualization", "power bi", "tableau",
             "dashboard", "sql", "microsoft excel", "excel", "looker", "dbt", "snowflake",
             "bigquery", "etl", "statistics", "data science", "data engineering", "pandas"],
}
ALIASES = {"amazon web services": "AWS", "retrieval augmented generation": "RAG"}
VOCAB = sorted({s for c in CATEGORIES.values() for s in c["skills"]})


def fetch() -> None:
    """Anonymous Kaggle downloads of the listed files; existing files are kept."""
    for folder, (ref, files, *_ ) in SOURCES.items():
        for name in files:
            target = RAW / folder / name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://www.kaggle.com/api/v1/datasets/download/{ref}/{name}"
            print(f"downloading {ref}/{name}", flush=True)
            with urllib.request.urlopen(url, timeout=600) as r:
                data = r.read()
            if data[:2] == b"PK" and not name.endswith(".xlsx"):  # CSVs arrive zipped
                import io
                import zipfile
                data = zipfile.ZipFile(io.BytesIO(data)).read(name)
            target.write_bytes(data)


_WORDS = {c: [re.compile(rf"(?<![\w.]){re.escape(w)}(?![\w.])") for w in words]
          for c, words in CATEGORY_WORDS.items()}


def category(text: str) -> str:
    """Most matched category ("excel" does not match "excellent", nor "sql" "postgresql")."""
    text = text.lower()
    hits = {c: sum(bool(rx.search(text)) for rx in rxs) for c, rxs in _WORDS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] else "other"


def vocab_skills(tags: list[str]) -> list[str]:
    """Upwork skill tags mapped onto the 39-skill GigSim vocabulary the personas use."""
    text = ", ".join(tags).lower()
    return sorted(set(mentioned_skills(text, VOCAB))
                  | {s for alias, s in ALIASES.items() if alias in text})


def clean(text: str) -> str:
    """HTML entities decoded, whitespace collapsed, emails and phone numbers masked."""
    return redact(re.sub(r"\s+", " ", html.unescape(text or "")).strip())


def money(text: str) -> float | None:
    m = re.search(r"[\d,]+(?:\.\d+)?", text or "")
    return (float(m.group().replace(",", "")) or None) if m else None


def _id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def quantiles(values: list[float]) -> dict | None:
    values = sorted(v for v in values if v and v > 0)
    if len(values) < 20:
        return None
    q = statistics.quantiles(values, n=20)  # q[4] = p25, q[9] = p50, q[14] = p75
    return {"n": len(values), "p25": round(q[4], 2), "p50": round(q[9], 2),
            "p75": round(q[14], 2)}


# --- posted budgets (200k) and paid contracts (1.3M): fair price bands -----------------

def market_rates() -> dict:
    fixed, hourly, paid, paid_rate = (defaultdict(list) for _ in range(4))
    for path in sorted((RAW / "upwork-200k").glob("*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8")):
            cat = category(r["title"])
            if r["is_hourly"] == "True":
                lo, hi = money(r["hourly_low"]), money(r["hourly_high"])
                if lo and hi:
                    hourly[cat].append((lo + hi) / 2)
            elif b := money(r["budget"]):
                fixed[cat].append(b)
    for r in csv.DictReader((RAW / "contracts" / "contracts.csv").open(encoding="utf-8")):
        cat = category(r["job_title"])
        if p := money(r["total_paid"]):
            paid[cat].append(p)
        if h := money(r["hourly_rate"]):
            paid_rate[cat].append(h)
    return {cat: {"posted_fixed_usd": quantiles(fixed[cat]),
                  "posted_hourly_mid_usd": quantiles(hourly[cat]),
                  "contract_paid_usd": quantiles(paid[cat]),
                  "contract_hourly_usd": quantiles(paid_rate[cat])}
            for cat in [*CATEGORY_WORDS, "other"]}


def fair_band(rates: dict, cat: str, hourly: bool) -> list[float] | None:
    q = rates[cat]["posted_hourly_mid_usd" if hourly else "posted_fixed_usd"]
    return [q["p25"], q["p75"]] if q else None


# --- 60k jobs with client fields: GigSim real mode ---------------------------------------

def gigsim_records(rates: dict, scraped: datetime) -> list[dict]:
    """One {"job", "client"} pair per posting. The dataset has no client ids, so each posting
    gets its own client record. Real: title, description, skill tags, budget, Connects,
    payment verification, spend, rating, feedback count, country. Synthetic (listed in
    "_synthetic"): hire rate, jobs posted, member since, reply preferences."""
    rng, out, seen = random.Random(42), [], set()
    path = RAW / "upwork-60k" / "Final_Upwork_Dataset.csv"
    for n, r in enumerate(csv.DictReader(path.open(encoding="utf-8-sig"))):
        if not r["Job Title"] or not r["Description"]:
            continue
        tags = [r[f"Category_{i}"] for i in range(1, 10) if r[f"Category_{i}"]]
        key = _id(r["Job Title"], r["Description"][:300])
        if key in seen:  # the scrape repeats postings across search keywords
            continue
        seen.add(key)
        hourly = r["Payment_type"] == "Hourly"
        lo, hi = money(r["Start_rate"]), money(r["End_rate"] or r["Hourly_Rate"])
        bmin, bmax = (lo, hi or lo) if hourly else (None, money(r["Job_Cost"]))
        cat = category(" ".join([r["Job Title"], *tags]))
        mins = re.match(r"(\d+) (minute|hour|day)", r["Posted_from"])
        ago = timedelta(**{f"{mins[2]}s": int(mins[1])}) if mins else timedelta(days=1)
        feedback = int(money(r["Feedback_Num"]) or 0)
        client = {
            "id": f"rc_{key}", "name": f"Upwork client {n}",
            "country": r["Client_Country"] or "unknown",
            "payment_verified": r["Payment_Situation"] == "Payment verified",
            "total_spend": money(r["Spent($)"]) or 0.0,
            "rating": round(float(r["Rating"]), 2) if r["Rating"] else None,
            "reviews": [],
            # Synthetic fill-ins: the scrape has no hire rate, job count or account age.
            "hire_rate": round(rng.uniform(0.3, 0.9), 2) if feedback else 0.0,
            "jobs_posted": max(feedback, 1),
            "member_since": (scraped - timedelta(days=rng.randint(30, 3000))).isoformat(),
            "_prefs": {"dislikes_generic_opening": rng.random() < 0.6,
                       "budget_ceiling_pct": round(rng.uniform(0.9, 1.3), 2)},
            "_source": "upwork-60k",
            "_synthetic": ["hire_rate", "jobs_posted", "member_since", "_prefs"]}
        budget = bmax or 0
        job = {
            "id": f"rj_{key}", "title": clean(r["Job Title"]),
            "description": clean(r["Description"]), "skills": tags,
            "budget_type": "hourly" if hourly else "fixed",
            "budget_min": bmin, "budget_max": bmax,
            "posted_at": (scraped - ago).isoformat(),
            "connects_cost": int(money(r["New_Connects_Num"]) or
                                 (16 if budget >= 5000 else 8 if budget >= 1000 else 4)),
            "client_id": client["id"], "screening_questions": [],
            "_truth": {"category": cat, "scam": None, "injection": False, "duplicate_of": None,
                       "fair_band": fair_band(rates, cat, hourly),
                       "experience_level": r["EX_level_demand"] or None,
                       "applicants": r["Applicants_Num"] or None},
            "_source": "upwork-60k", "_synthetic": ["posted_at (relative age only)"]}
        out.append({"job": job, "client": client})
    return out


# --- 50k jobs (2024): real-job retrieval labels ------------------------------------------

def parse_50k(desc: str) -> tuple[str, list[str], str]:
    """The 50k scrape appends "Budget: ... Category: ... Skills: a, b ... Country: ..." to
    each description. Returns (body, skill tags, Upwork category)."""
    body = re.split(r"(?:Budget|Hourly Range|Posted On):", desc, maxsplit=1)[0]
    cat = re.search(r"Category: (.*?)Skills:", desc)
    skills = re.search(r"Skills:(.*?)(?:Skills:|Location Requirement:|Country:|click to apply)",
                       desc, re.DOTALL)
    tags = [t.strip() for t in skills[1].split(",") if t.strip()] if skills else []
    return body, tags, cat[1].strip() if cat else ""


def retrieval_set(per_persona: int = 200) -> list[dict]:
    """Same labelling rule as evals/datasets/dev_retrieval.jsonl, on real 2024 postings:
    a project is relevant when it truly has max(2, ceil(0.6 x skills)) of the job's skills,
    with the job's Upwork tags mapped onto the GigSim vocabulary."""
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    personas = {"fr_ml": "ml", "fr_fs": "fullstack", "fr_da": "data"}
    rows = sorted(csv.DictReader((RAW / "upwork-50k" / "upwork-jobs.csv").open(encoding="utf-8")),
                  key=lambda r: r["published_date"])
    picked, out, seen = Counter(), [], set()
    for r in rows:
        body, tags, upwork_cat = parse_50k(r["description"])
        need = vocab_skills(tags)
        key = _id(r["title"], body[:300])
        if len(need) < 2 or key in seen:
            continue
        seen.add(key)
        cat = category(" ".join([r["title"], upwork_cat, *tags]))
        for fid, pcat in personas.items():
            if cat != pcat or picked[fid] >= per_persona:
                continue
            gains = {pid: len(set(need) & set(t["skills"])) for pid, t in truth.items()
                     if t["persona"] == fid}
            enough = max(2, math.ceil(0.6 * len(need)))
            relevant = {pid: g for pid, g in gains.items() if g >= enough}
            if relevant:
                picked[fid] += 1
                out.append({"persona": fid, "job_id": f"r50_{key}", "skills": need,
                            "upwork_tags": tags,
                            "query": f"{clean(r['title'])}\n\n{clean(body)}",
                            "relevant": relevant, "_source": "upwork-50k"})
    return out


# --- labelled real and fake postings: scam detection -------------------------------------

TEMPLATED = re.compile(r"earn \d+ ?week|immediate hiring contact now")


def scam_set() -> list[dict]:
    """Every labelled posting. "templated" marks the near-identical generated fakes
    ("... earn 5000week immediate hiring contact now at ..."), so results can be split."""
    import openpyxl
    wb = openpyxl.load_workbook(RAW / "fake-jobs" / SOURCES["fake-jobs"][1][0], read_only=True)
    rows = wb.worksheets[0].iter_rows(values_only=True)
    header = next(rows)
    out = []
    for values in rows:
        r = dict(zip(header, values, strict=False))
        if r["fraudulent"] not in (0, 1) or not r["job_desc"]:
            continue
        text = " ".join(str(r[k]) for k in ("job_desc", "skills_desc") if r[k])
        out.append({"id": f"fj_{len(out):05d}", "title": str(r["job_title"] or ""),
                    "text": clean(text), "fraudulent": r["fraudulent"],
                    "templated": bool(TEMPLATED.search(text)),
                    "salary_range": r["salary_range"], "_source": "fake-jobs"})
    return out


# --- benchmarks ------------------------------------------------------------------------

def freelancer_rates() -> dict:
    by_skill = defaultdict(list)
    path = RAW / "freelancer-success" / "freelancer_gig_success_dataset.csv"
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if h := money(r["hourly_rate_usd"]):
            by_skill[r["primary_skill"]].append(h)
    return {skill: quantiles(v) for skill, v in sorted(by_skill.items())}


def synthetic_rates() -> dict:
    """The same statistics for GigSim's synthetic jobs, for the realism comparison."""
    fixed, hourly = defaultdict(list), defaultdict(list)
    for j in seed.build()["jobs"].values():
        target = hourly if j["budget_type"] == "hourly" else fixed
        value = ((j["budget_min"] or 0) + j["budget_max"]) / 2 if j["budget_type"] == "hourly" \
            else j["budget_max"]
        target[j["_truth"]["category"]].append(value)
    return {c: {"posted_fixed_usd": quantiles(fixed[c]),
                "posted_hourly_mid_usd": quantiles(hourly[c])} for c in CATEGORIES}


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    fetch()
    OUT.mkdir(parents=True, exist_ok=True)
    rates = market_rates()
    # The 60k scrape ran in February and March 2023; posting ages are relative to it.
    gigsim_rows = gigsim_records(rates, datetime(2023, 3, 15, tzinfo=UTC))
    retrieval, scams = retrieval_set(), scam_set()
    _jsonl(OUT / "gigsim.jsonl", gigsim_rows)
    _jsonl(OUT / "retrieval_real.jsonl", retrieval)
    _jsonl(OUT / "scam_real.jsonl", scams)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {f: {"kaggle": f"https://www.kaggle.com/datasets/{ref}", "files": files,
                        "license": lic, "use": use}
                    for f, (ref, files, lic, use) in SOURCES.items()},
        "gigsim_real": {
            "jobs": len(gigsim_rows),
            "by_category": Counter(r["job"]["_truth"]["category"] for r in gigsim_rows),
            "hourly_share": round(sum(r["job"]["budget_type"] == "hourly"
                                      for r in gigsim_rows) / len(gigsim_rows), 3),
            "payment_verified_share": round(sum(r["client"]["payment_verified"]
                                                for r in gigsim_rows) / len(gigsim_rows), 3),
            "zero_spend_share": round(sum(r["client"]["total_spend"] == 0
                                          for r in gigsim_rows) / len(gigsim_rows), 3)},
        "retrieval_real": {"queries": len(retrieval),
                           "per_persona": Counter(r["persona"] for r in retrieval),
                           "mean_relevant": round(statistics.mean(
                               len(r["relevant"]) for r in retrieval), 2)},
        "scam_real": {"postings": len(scams), "fraudulent": sum(r["fraudulent"] for r in scams),
                      "templated_fakes": sum(r["templated"] for r in scams)},
        "market_rates_real": rates,
        "market_rates_gigsim_synthetic": synthetic_rates(),
        "freelancer_hourly_rates_synthetic_dataset": freelancer_rates(),
    }
    SUMMARY.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("gigsim_real", "retrieval_real", "scam_real")},
                     indent=1))


if __name__ == "__main__":
    main()
