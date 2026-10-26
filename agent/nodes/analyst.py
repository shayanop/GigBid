"""Job Analyst: job post -> JobSpec."""

from agent.handoffs import JobSpec
from agent.nodes import common


@common.node("analyst")
async def analyze(state: dict) -> dict:
    return {"spec": await common.ask("analyst", JobSpec, common.job_block(state["job"]))}
