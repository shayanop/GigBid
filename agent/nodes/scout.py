"""Scout (graph entry): loads the job the scheduler queued. Saved-search scouting and
dedup run in the worker."""

from agent.marketplace_port import Job
from agent.nodes import common


@common.node("scout")
async def load_job(state: dict) -> dict:
    job = await common.toolbox().call("scout", "marketplace", "get_job",
                                      {"job_id": state["job_id"]})
    return {"job": Job.model_validate(job), "status": "analyzing", "revisions": 0}
