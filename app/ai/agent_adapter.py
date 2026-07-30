import hashlib
import json
import time
from dataclasses import dataclass

from app.agents.protocol import StructuredAgentClient, StructuredResult
from app.ai.client import GeminiClient
from app.core.errors import CrawlerError, ErrorCode
from app.models.content import assert_safe_content_payload
from app.repositories.agent_audit import AgentAuditRepository


@dataclass(frozen=True, slots=True)
class AgentModelPolicy:
    navigation: str
    disease_detector: str
    disease_extraction: str
    normalization: str

    def model_for(self, agent_name: str) -> str:
        mapping = {
            "navigation": self.navigation,
            "autocomplete_selection": self.navigation,
            "disease_detector": self.disease_detector,
            "disease_extraction": self.disease_extraction,
            "normalization": self.normalization,
        }
        try:
            return mapping[agent_name]
        except KeyError as exc:
            raise ValueError(f"Unknown Gemini agent: {agent_name}") from exc


class GeminiAgentAdapter(StructuredAgentClient):
    """Bind pure agent contracts to Gemini with per-job audit and budgets."""

    def __init__(
        self,
        *,
        client: GeminiClient,
        models: AgentModelPolicy,
        audit: AgentAuditRepository,
        job_id: str,
        max_calls: int,
    ) -> None:
        self.client = client
        self.models = models
        self.audit = audit
        self.job_id = job_id
        self.max_calls = max_calls
        self.call_count = 0

    async def generate_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        payload: dict[str, object],
        response_model: type[StructuredResult],
    ) -> StructuredResult:
        if self.call_count >= self.max_calls:
            raise CrawlerError(
                ErrorCode.AGENT_BUDGET_EXHAUSTED,
                "Gemini model-call budget was exhausted",
            )
        assert_safe_content_payload(payload)
        model = self.models.model_for(agent_name)
        prompt_version = str(payload.get("prompt_version", "unknown"))
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        input_hash = hashlib.sha256(serialized.encode()).hexdigest()
        full_prompt = f"{prompt}\n\nINPUT_JSON:\n{serialized}"
        self.call_count += 1
        started = time.monotonic()
        try:
            result = await self.client.generate_structured(
                model=model,
                prompt=full_prompt,
                response_schema=response_model,
                temperature=0,
            )
        except CrawlerError as exc:
            await self.audit.record_model_call(
                job_id=self.job_id,
                agent_name=agent_name,
                model_id=model,
                prompt_version=prompt_version,
                input_hash=input_hash,
                latency_ms=round((time.monotonic() - started) * 1_000),
                status="failure",
                error_code=exc.code.value,
            )
            raise
        output_payload = json.dumps(
            result.value.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        await self.audit.record_model_call(
            job_id=self.job_id,
            agent_name=agent_name,
            model_id=result.model_id,
            prompt_version=prompt_version,
            input_hash=input_hash,
            output_hash=hashlib.sha256(output_payload.encode()).hexdigest(),
            latency_ms=result.latency_ms,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            status="success",
        )
        return result.value
