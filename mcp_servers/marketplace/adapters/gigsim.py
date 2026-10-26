"""MarketplacePort over the GigSim REST API, with bounded retries on 429/5xx."""

import asyncio
from datetime import datetime

import httpx

from agent.marketplace_port import (Client, Job, JobPage, MarketplaceError,
                                    MarketplaceUnavailable, Message, Proposal, ProposalIn, Thread)

RETRY_STATUS = {429, 500, 502, 503, 504}


class GigSimAdapter:
    def __init__(self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None,
                 attempts: int = 4, backoff: float = 0.5, timeout: float = 10.0):
        self._http = dict(base_url=base_url, transport=transport, timeout=timeout,
                          headers={"Authorization": f"Bearer {token}"})
        self.attempts, self.backoff = attempts, backoff

    async def _call(self, method: str, path: str, idempotency_key: str | None = None, **kw):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        async with httpx.AsyncClient(**self._http) as http:
            for attempt in range(self.attempts):
                last = attempt == self.attempts - 1
                try:
                    r = await http.request(method, path, headers=headers, **kw)
                except httpx.TransportError as e:
                    if last:
                        raise MarketplaceUnavailable(f"GigSim unreachable: {e}") from e
                else:
                    if r.status_code not in RETRY_STATUS:
                        if r.is_error:
                            raise MarketplaceError(f"{r.status_code}: {r.json().get('detail')}")
                        return r.json()
                    if last:
                        raise MarketplaceUnavailable(f"GigSim returned {r.status_code}")
                    # Writes are safe to retry: GigSim dedupes on the idempotency key.
                    if retry_after := r.headers.get("Retry-After"):
                        await asyncio.sleep(min(float(retry_after), 10.0))
                        continue
                await asyncio.sleep(min(self.backoff * 2**attempt, 8.0))

    async def search_jobs(self, query: str, skills: list[str], posted_after: datetime | None,
                          limit: int, offset: int) -> JobPage:
        params = {"q": query, "skills": ",".join(skills), "limit": limit, "offset": offset}
        if posted_after:
            params["posted_after"] = posted_after.isoformat()
        return JobPage.model_validate(await self._call("GET", "/jobs", params=params))

    async def get_job(self, job_id: str) -> Job:
        return Job.model_validate(await self._call("GET", f"/jobs/{job_id}"))

    async def get_client(self, client_id: str) -> Client:
        return Client.model_validate(await self._call("GET", f"/clients/{client_id}"))

    async def get_connects(self) -> int:
        return (await self._call("GET", "/me/connects"))["balance"]

    async def list_threads(self) -> list[Thread]:
        return [Thread.model_validate(t) for t in await self._call("GET", "/threads")]

    async def create_proposal_draft(self, draft: ProposalIn, idempotency_key: str) -> Proposal:
        data = await self._call("POST", "/proposals", idempotency_key, json=draft.model_dump())
        return Proposal.model_validate(data)

    async def submit_proposal(self, proposal_id: str, idempotency_key: str) -> Proposal:
        data = await self._call("POST", f"/proposals/{proposal_id}/submit", idempotency_key)
        return Proposal.model_validate(data)

    async def send_message(self, thread_id: str, body: str, idempotency_key: str) -> Message:
        data = await self._call("POST", f"/threads/{thread_id}/messages", idempotency_key,
                                json={"body": body})
        return Message.model_validate(data)
