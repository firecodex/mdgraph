"""Rule-based, deterministic offline compiler for MdGraph."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from mdgraph.compiler.base import BaseCompiler
from mdgraph.models import OKFConcept, normalize_node_id


class RuleBasedCompiler(BaseCompiler):
    """Deterministic compiler that extracts concepts from markdown sections and builds cross-links."""

    def compile(
        self,
        text: str,
        source_name: str | None = None,
        tenant_id: str | None = "default",
    ) -> list[OKFConcept]:
        tenant_id = tenant_id or "default"
        # Split text by Markdown headers (# or ##)
        header_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        matches = list(header_pattern.finditer(text))

        if not matches:
            # Single concept document
            fallback_id = normalize_node_id(source_name or "concept_document")
            rel_file = f"tenants/{tenant_id}/concepts/{fallback_id}.md" if tenant_id != "default" else f"concepts/{fallback_id}.md"
            concept = OKFConcept(
                tenant_id=tenant_id,
                id=fallback_id,
                type="Concept",
                title=(source_name or "Concept Document").replace("_", " ").title(),
                description=text[:160].replace("\n", " ").strip() + "...",
                tags=["ingested", "document"],
                status="stable",
                body=text.strip(),
                file_path=rel_file,
            )
            return [concept]

        sections = []
        for i, match in enumerate(matches):
            level = len(match.group(1))
            raw_title = match.group(2).strip()
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_body = text[start_pos:end_pos].strip()

            node_id = normalize_node_id(raw_title)
            # Infer type based on keywords
            inferred_type = "Concept"
            lower_title = raw_title.lower()
            if "policy" in lower_title or "rules" in lower_title:
                inferred_type = "Policy"
            elif "architecture" in lower_title or "pipeline" in lower_title:
                inferred_type = "Architecture"
            elif "system" in lower_title or "server" in lower_title or "engine" in lower_title:
                inferred_type = "System"
            elif "tool" in lower_title or "api" in lower_title or "cli" in lower_title:
                inferred_type = "Tool"
            elif "metric" in lower_title:
                inferred_type = "Metric"

            sections.append({
                "id": node_id,
                "title": raw_title,
                "type": inferred_type,
                "body": section_body,
                "level": level,
            })

        # Discover cross-references between sections
        all_ids = {s["id"]: s["title"] for s in sections}

        concepts: list[OKFConcept] = []
        for sec in sections:
            body = sec["body"]
            # Auto-link mentions of other sections if not already linked
            for other_id, other_title in all_ids.items():
                if other_id != sec["id"] and len(other_title) > 3:
                    # If other title appears in body and isn't already inside a markdown link
                    if other_title.lower() in body.lower() and f"({other_id}.md)" not in body:
                        # Replace first occurrence with markdown link
                        pattern = re.compile(re.escape(other_title), re.IGNORECASE)
                        body = pattern.sub(f"[{other_title}](./{other_id}.md)", body, count=1)

            first_sentence = body.split(". ")[0].replace("\n", " ").strip()
            if len(first_sentence) > 160:
                first_sentence = first_sentence[:157] + "..."
            description = first_sentence or f"Specification for {sec['title']}"

            now_iso = datetime.now(timezone.utc).isoformat()
            file_path = f"tenants/{tenant_id}/concepts/{sec['id']}.md" if tenant_id != "default" else f"concepts/{sec['id']}.md"
            concept = OKFConcept(
                okf_version="0.2",
                tenant_id=tenant_id,
                id=sec["id"],
                type=sec["type"],
                title=sec["title"],
                description=description,
                tags=[sec["type"].lower(), "auto-extracted"],
                status="stable",
                generated={"by": "compiler:rule-based", "at": now_iso},
                sources=[source_name] if source_name else [],
                body=f"# {sec['title']}\n\n{body}",
                file_path=file_path,
            )
            # Re-extract explicit edges tagged with tenant_id
            concept.edges = OKFConcept.extract_links(concept.id, concept.body, tenant_id=tenant_id)
            concepts.append(concept)

        return concepts
