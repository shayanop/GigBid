"""Optional OpenTelemetry export to Arize Phoenix (E3).

Off unless PHOENIX_COLLECTOR_ENDPOINT is set (compose runs Phoenix on :6006; Phoenix Cloud
takes OTEL_EXPORTER_OTLP_HEADERS for its API key). When on, every LangChain and LangGraph
run, so every graph node and model call with its token counts, becomes a span.

Each run is tagged with GigBid's own trace id as the session id. The same id is on the API
response (X-Trace-Id), the worker job, every MCP call and the marketplace audit log, so one
id finds a run everywhere. Span attributes pass through agent.redact before export, so
emails and phone numbers in job text never reach the trace store (E4).
"""

import contextlib
import os

from agent.redact import redact

_enabled = False


class _Redacting:
    """SpanExporter wrapper: masks PII in string attributes of every span it exports."""

    def __init__(self, inner):
        self.inner = inner

    def export(self, spans):
        from opentelemetry.sdk.trace import ReadableSpan
        clean = [ReadableSpan(
            name=s.name, context=s.context, parent=s.parent, resource=s.resource,
            attributes={k: redact(v) if isinstance(v, str) else v
                        for k, v in (s.attributes or {}).items()},
            events=s.events, links=s.links, kind=s.kind, status=s.status,
            start_time=s.start_time, end_time=s.end_time,
            instrumentation_scope=s.instrumentation_scope) for s in spans]
        return self.inner.export(clean)

    def shutdown(self):
        return self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        return self.inner.force_flush(timeout_millis)


def setup(service: str, exporter=None) -> bool:
    """Starts export for this process when PHOENIX_COLLECTOR_ENDPOINT is set. Tests pass an
    in-memory exporter instead of the OTLP one."""
    global _enabled
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
    if not endpoint or _enabled:
        return _enabled
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource({
        "service.name": service,
        "openinference.project.name": os.getenv("PHOENIX_PROJECT_NAME", "gigbid")}))
    exporter = exporter or OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(_Redacting(exporter)))
    trace.set_tracer_provider(provider)
    LangChainInstrumentor().instrument(tracer_provider=provider)
    _enabled = True
    return True


def session(trace_id: str | None):
    """Tags every span in this block with GigBid's trace id; a no-op when tracing is off."""
    if not (_enabled and trace_id):
        return contextlib.nullcontext()
    from openinference.instrumentation import using_session
    return using_session(trace_id)
