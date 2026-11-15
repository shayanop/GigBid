"""Phoenix tracing (E3, E4): runs carry GigBid's trace id and PII never leaves in a span."""

from langchain_core.runnables import RunnableLambda
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent import tracing


def test_spans_carry_the_trace_id_and_are_redacted(monkeypatch):
    from openinference.instrumentation.langchain import LangChainInstrumentor
    memory = InMemorySpanExporter()
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://unused")
    try:
        assert tracing.setup("test", exporter=memory)
        with tracing.session("trace-0123456789"):
            RunnableLambda(lambda x: x.upper()).invoke("mail sana@example.com or +1 555 0100")
        trace.get_tracer_provider().force_flush()
        spans = memory.get_finished_spans()
        assert spans and all(s.attributes.get("session.id") == "trace-0123456789" for s in spans)
        text = " ".join(str(v) for s in spans for v in s.attributes.values())
        assert "sana@example.com" not in text and "555 0100" not in text and "[REDACTED]" in text
    finally:
        LangChainInstrumentor().uninstrument()
        tracing._enabled = False


def test_session_is_a_no_op_when_tracing_is_off():
    with tracing.session("trace-0123456789"):
        pass
