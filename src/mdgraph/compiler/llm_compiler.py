"""Pluggable LLM-driven compiler powered by LiteLLM."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import litellm

from mdgraph.compiler.base import BaseCompiler
from mdgraph.compiler.mock_compiler import RuleBasedCompiler
from mdgraph.compiler.prompt import COMPILER_SYSTEM_PROMPT, JSON_SCHEMA_INSTRUCTION
from mdgraph.models import OKFConcept, normalize_node_id


class LLMCompiler(BaseCompiler):
    """Compiles unstructured/normalized documents into OKF concepts using LiteLLM."""

    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        temperature: float = 0.1,
        api_key: str | None = None,
        fallback_to_rules: bool = True,
    ):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.fallback_to_rules = fallback_to_rules
        self._rule_compiler = RuleBasedCompiler()

    def compile(
        self,
        text: str,
        source_name: str | None = None,
        tenant_id: str | None = "default",
    ) -> list[OKFConcept]:
        """Compile document into OKF concepts via LiteLLM scoped to tenant."""
        tenant_id = tenant_id or "default"
        if not text.strip():
            return []

        # If no relevant API keys are set and local model not configured, fallback gracefully if enabled
        has_key = bool(
            self.api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or "ollama" in self.model.lower()
            or "local" in self.model.lower()
        )

        if not has_key and self.fallback_to_rules:
            return self._rule_compiler.compile(text, source_name=source_name, tenant_id=tenant_id)

        try:
            return self._call_llm(text, source_name, tenant_id=tenant_id)
        except Exception as e:
            if self.fallback_to_rules:
                return self._rule_compiler.compile(text, source_name=source_name, tenant_id=tenant_id)
            raise RuntimeError(f"LLM compilation failed: {e}") from e

    def _call_llm(self, text: str, source_name: str | None, tenant_id: str | None = "default") -> list[OKFConcept]:
        tenant_id = tenant_id or "default"
        user_prompt = f"Source Document: {source_name or 'Unspecified'}\n\n{text}\n\n{JSON_SCHEMA_INSTRUCTION}"

        messages = [
            {"role": "system", "content": COMPILER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Try structured json output
        try:
            kwargs["response_format"] = {"type": "json_object"}
            response = litellm.completion(**kwargs)
        except Exception:
            # Retry without response_format if provider doesn't support json_object mode
            kwargs.pop("response_format", None)
            response = litellm.completion(**kwargs)

        raw_output = response.choices[0].message.content or ""
        return self._parse_llm_json(raw_output, source_name, tenant_id=tenant_id)

    def _parse_llm_json(self, raw_output: str, source_name: str | None, tenant_id: str = "default") -> list[OKFConcept]:
        # Extract json substring if wrapped in markdown ```json
        content = raw_output.strip()
        if "```json" in content:
            content = content.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in content:
            content = content.split("```", 1)[1].split("```", 1)[0].strip()

        data = json.loads(content)
        concepts_data = data.get("concepts", [])
        if not concepts_data and isinstance(data, list):
            concepts_data = data

        now_iso = datetime.now(timezone.utc).isoformat()
        results: list[OKFConcept] = []
        for item in concepts_data:
            node_id = normalize_node_id(item.get("id") or item.get("title") or "concept")
            body = item.get("body", "").strip()
            concept_type = item.get("type", "Concept")
            title = item.get("title", node_id.replace("_", " ").title())
            desc = item.get("description", "")
            tags = item.get("tags", [])
            status = item.get("status", "stable")
            resource = item.get("resource")
            stale_after = item.get("stale_after")

            file_path = f"tenants/{tenant_id}/concepts/{node_id}.md" if tenant_id != "default" else f"concepts/{node_id}.md"
            concept = OKFConcept(
                okf_version="0.2",
                tenant_id=tenant_id,
                id=node_id,
                type=concept_type,
                title=title,
                description=desc,
                resource=resource,
                tags=tags,
                status=status,
                stale_after=stale_after,
                generated={"by": f"agent:{self.model}", "at": now_iso},
                sources=[source_name] if source_name else [],
                body=body,
                file_path=file_path,
            )
            concept.edges = OKFConcept.extract_links(concept.id, concept.body, tenant_id=tenant_id)
            results.append(concept)

        return results
