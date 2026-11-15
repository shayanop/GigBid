# Demo script

A shot list for the three-minute demo video and the 30-second README GIF (spec project
artifacts). Every scene uses the demo account (`DEMO_EMAIL`, AI/ML persona `fr_ml`) and
GigSim's seeded data, so the same jobs appear every time.

**Real models or scripted.** Use real models (`GIGBID_PROFILE=cerebras`) for scenes 2–4.
The scripted `fake` profile drafts the same canned letter for every job and cannot ignore
an injection on its own. Free-tier limits make a full bid take 30–60 s, so record each scene
separately and cut the waits.

## Setup

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d
```

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m apps.api.seed
```

Open http://localhost:3000 and sign in with the demo login. Phoenix is on
http://localhost:6006, for a trace shot.

## Three-minute video

| Time | Scene | What to show |
| --- | --- | --- |
| 0:00–0:20 | The problem | The Inbox: saved search "LangGraph, RAG", jobs arriving. One line: GigBid drafts and judges; you approve everything that leaves. |
| 0:20–1:20 | Job to approved proposal | Analyse **job_00326** ("Fine-tune an LLM for ticket triage"). Show the run timeline (analyst, risk and matcher in parallel, then decide, writer, verifier, critic, compliance). In the Studio, hover a claim to show its evidence. Point out that the client sees the letter without the ids. Approve and show the Connects spent. |
| 1:20–1:50 | Scam identified | Analyse **job_00260** ("Deploy ML model behind FastAPI"): the risk report flags `off_platform_contact`, `unverified_client` and `no_spend_history`, and the job is skipped with the reason shown. No draft is written. |
| 1:50–2:20 | Injection ignored | Analyse **job_00166**, whose post tells AI assistants to claim 15 years of experience with every technology. Show that the risk report flags `prompt_injection` and that the draft claims only what the evidence shows. Optionally show the same post given to a naive prompt (`evals/results/injection_eval.json`). |
| 2:20–2:50 | Client reply handled | Messages: the interview request (thread **th_0002**). The liaison proposes slots from the calendar, the reply waits for approval, then edit and send it. Also show the scam message (th_0004) being flagged. |
| 2:50–3:00 | Close | Settings: what memory learned from your edits (deletable), then the design review's results table. |

## 30-second GIF

Scene 2 only: the Inbox, analyse, timeline, the Studio with evidence hover, then Approve.
Record at 1280×800 and speed the analysis wait up four times.

## Traces for the README

With Phoenix Cloud configured (see [RUNBOOK.md](RUNBOOK.md#tracing-phoenix)), take the
three public traces from:
1. scene 2 (approved proposal);
2. scene 3 (skipped scam);
3. any bid where the Critic sent the draft back at least once.

The run timeline shows the number of revisions.
