from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
)

from ...engine import FieldSpec
from ..schemas import (
    ExtractDecisionResponse,
    ExtractRequest,
    ExtractResponse,
)

from .context import RouteContext



def register_extract_routes(router: APIRouter, context: RouteContext) -> None:
    runtime = context.runtime
    map_service_error = context.map_service_error

    @router.post(
        "/extract",
        response_model=ExtractResponse,
        tags=["extraction"],
    )
    def extract_endpoint(
        payload: ExtractRequest,
        runtime_service=Depends(runtime),
    ):
        fields = [
            FieldSpec(
                key=field.key,
                required=field.required,
                value_type=field.value_type,
                min_confidence=field.min_confidence,
                min_margin=field.min_margin,
                aliases=tuple(field.aliases),
            )
            for field in payload.fields
        ]
        warnings: list[str] = []
        try:
            if payload.url:
                url_kwargs = {"url": payload.url, "fields": fields}
                if payload.use_model:
                    url_kwargs["use_model"] = True
                pipeline_result = runtime_service.extract_url(**url_kwargs)
                result = pipeline_result.extraction
                warnings = list(pipeline_result.acquisition.warnings)
            else:
                extract_kwargs = {
                    "asset_id": payload.asset_id,
                    "source_url": payload.source_url,
                    "text": payload.text,
                    "html": payload.html,
                    "attributes": payload.attributes,
                    "fields": fields,
                }
                if payload.use_model:
                    extract_kwargs["use_model"] = True
                result = runtime_service.extract(**extract_kwargs)
        except Exception as exc:
            raise map_service_error(exc) from exc

        decisions = {
            key: ExtractDecisionResponse(
                status=decision.status.value,
                selected_value=(decision.selected.value if decision.selected is not None else None),
                selected_candidate_id=(
                    decision.selected.candidate_id if decision.selected is not None else None
                ),
                confidence=(
                    decision.selected.confidence if decision.selected is not None else None
                ),
                provider=(decision.selected.provider if decision.selected is not None else None),
                evidence=(
                    [
                        {
                            "kind": evidence.kind,
                            "source_ref": evidence.source_ref,
                            "excerpt": evidence.excerpt,
                            "metadata": dict(evidence.metadata),
                        }
                        for evidence in decision.selected.evidence
                    ]
                    if decision.selected is not None
                    else []
                ),
                candidates=[
                    {
                        "candidate_id": candidate.candidate_id,
                        "value": candidate.value,
                        "confidence": candidate.confidence,
                        "provider": candidate.provider,
                        "evidence": [
                            {
                                "kind": evidence.kind,
                                "source_ref": evidence.source_ref,
                                "excerpt": evidence.excerpt,
                                "metadata": dict(evidence.metadata),
                            }
                            for evidence in candidate.evidence
                        ],
                    }
                    for candidate in decision.candidates
                ],
                reason=decision.reason,
            )
            for key, decision in result.decisions.items()
        }
        return ExtractResponse(
            values=result.values(include_unconfirmed=True),
            requires_confirmation=result.requires_confirmation,
            unresolved_required_fields=list(result.unresolved_required_fields),
            decisions=decisions,
            provider_errors=dict(result.provider_errors),
            warnings=warnings,
        )
