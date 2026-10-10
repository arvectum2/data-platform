from __future__ import annotations


from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from ..schemas import (
    IngestResponse,
    ProcessDocumentResponse,
    UrlIngestRequest,
)

from .context import RouteContext



def register_ingest_routes(router: APIRouter, context: RouteContext) -> None:
    resolved = context.settings
    runtime = context.runtime
    map_service_error = context.map_service_error

    @router.post(
        "/ingest/url",
        response_model=IngestResponse,
        tags=["ingest"],
    )
    def ingest_url_endpoint(
        payload: UrlIngestRequest,
        runtime_service=Depends(runtime),
    ):
        try:
            return runtime_service.ingest_url(
                collection_id=payload.collection_id,
                url=payload.url,
                title=payload.title,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/process/document",
        response_model=ProcessDocumentResponse,
        tags=["process"],
    )
    async def process_document_endpoint(
        collection_id: str = Form(...),
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
        canonical_uri: str | None = Form(default=None),
        chunk_size_chars: int = Form(default=1500, ge=1, le=200_000),
        overlap_chars: int = Form(default=200, ge=0, le=100_000),
        min_chunk_chars: int = Form(default=120, ge=1, le=200_000),
        max_chars: int = Form(default=2_000_000, ge=1, le=20_000_000),
        runtime_service=Depends(runtime),
    ):
        content = await file.read(resolved.max_upload_bytes + 1)
        if len(content) > resolved.max_upload_bytes:
            raise HTTPException(status_code=413, detail="uploaded document is too large")
        filename = file.filename or "document.bin"
        if overlap_chars >= chunk_size_chars:
            raise HTTPException(
                status_code=422,
                detail="overlap_chars must be smaller than chunk_size_chars",
            )
        try:
            return runtime_service.process_document_bytes(
                collection_id=collection_id,
                filename=filename,
                content=content,
                title=title,
                canonical_uri=canonical_uri,
                chunk_size_chars=chunk_size_chars,
                overlap_chars=overlap_chars,
                min_chunk_chars=min_chunk_chars,
                max_chars=max_chars,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc

    @router.post(
        "/ingest/document",
        response_model=IngestResponse,
        tags=["ingest"],
    )
    async def ingest_document_endpoint(
        collection_id: str = Form(...),
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
        canonical_uri: str | None = Form(default=None),
        pre_chunked: bool = Form(default=False),
        runtime_service=Depends(runtime),
    ):
        content = await file.read(resolved.max_upload_bytes + 1)
        if len(content) > resolved.max_upload_bytes:
            raise HTTPException(status_code=413, detail="uploaded document is too large")
        filename = file.filename or "document.bin"
        try:
            return runtime_service.ingest_document_bytes(
                collection_id=collection_id,
                filename=filename,
                content=content,
                title=title,
                canonical_uri=canonical_uri,
                pre_chunked=pre_chunked,
            )
        except Exception as exc:
            raise map_service_error(exc) from exc
