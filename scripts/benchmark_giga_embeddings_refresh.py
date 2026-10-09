#!/usr/bin/env python3
"""Model-native Giga-Embeddings Russian search evaluation.

Read-only eval of the same 45 Arvectum pages + 12 frozen Search Console cases
as benchmark_embedding_refresh.py. Does NOT touch production search indexes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

from benchmark_embedding_refresh import site_corpus

DEFAULT_MODEL = Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks/russian-models/giga-embeddings-0826-480m")
DEFAULT_SITE = Path("/Volumes/ArvectumSSD/Arvectum/repos/arvectum-site/public")
INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"


def main() -> int:
    arg=argparse.ArgumentParser()
    arg.add_argument("--model",type=Path,default=DEFAULT_MODEL)
    arg.add_argument("--site-public",type=Path,default=DEFAULT_SITE)
    arg.add_argument("--device",default="mps",choices=["mps","cpu"])
    arg.add_argument("--output",type=Path,required=True)
    a=arg.parse_args()
    suite=Path(__file__).resolve().parents[1]/"benchmarks/growth_search_console_v1.json"
    suite_data=suite.read_bytes()
    cases=json.loads(suite_data)["cases"]
    docs=site_corpus(a.site_public)
    assert len(docs)==45 and len(cases)==12,(len(docs),len(cases))
    expected=set(y for c in cases for y in c["expected_ids"])
    assert expected.issubset({d["uri"] for d in docs})
    base=Path(__file__).resolve().parents[1]/"benchmarks/results/model_refresh_2026-10-09/embedding-4b.json"
    baseline=json.loads(base.read_text())
    corpus_hash=hashlib.sha256(json.dumps(docs,sort_keys=True).encode()).hexdigest()
    assert baseline["site_corpus_hash"]==corpus_hash, "site corpus differs from prior benchmark!"
    assert baseline["suite_sha256"]==hashlib.sha256(suite_data).hexdigest()
    from sentence_transformers import SentenceTransformer
    print("LOAD",a.model,a.device,flush=True)
    before=time.perf_counter()
    model=SentenceTransformer(str(a.model),trust_remote_code=True,device=a.device,local_files_only=True)
    load_s=round(time.perf_counter()-before,3)
    print("LOADED",load_s,"seconds",flush=True)
    data=[d["text"] for d in docs]
    queries=[f"Instruct: {INSTRUCTION}\nQuery: {c['query']}" for c in cases]
    started=time.perf_counter()
    embeddings=model.encode(data,batch_size=2,normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True)
    doc_sec=round(time.perf_counter()-started,3)
    started=time.perf_counter()
    qvectors=model.encode(queries,batch_size=2,normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True)
    query_sec=round(time.perf_counter()-started,3)
    import numpy as np
    print("ENCODE_DONE",len(embeddings),len(qvectors),"DIM",embeddings.shape[1],flush=True)
    assert embeddings.shape==(45,1024) and qvectors.shape==(12,1024), "Unexpected embedding dimensions"
    sim=np.asarray(qvectors,dtype=np.float32)@np.asarray(embeddings,dtype=np.float32).T
    results=[]
    ranks=[]
    for i,c in enumerate(cases):
        order=np.argsort(-sim[i])
        uris=[docs[int(idx)]["uri"] for idx in order]
        rank=next((j+1 for j,uri in enumerate(uris) if uri in c["expected_ids"]),None)
        ranks.append(rank)
        results.append({"id":c["id"],"rank":rank,"expected":c["expected_ids"],"top5":uris[:5],"top1":uris[0]})
        print("CASE",c["id"],rank,flush=True)
    result={"model":"ai-sage/Giga-Embeddings-instruct-480M-0826","revision":"1763d603adac8057bd6482a708001b0ed2e0a903",
            "model_path":str(a.model),"backend":"sentence-transformers","device":a.device,
            "dtype":"bfloat16 original weights","pooling":"mean and L2 normalized, from model SentenceTransformer config",
            "query_instruction":INSTRUCTION,"document_instruction":None,
            "suite":"growth_search_console_v1","suite_sha256":hashlib.sha256(suite_data).hexdigest(),
            "site_corpus_hash":corpus_hash,"docs":len(docs),"queries":len(cases),"dimension":int(embeddings.shape[1]),
            "load_s":load_s,"documents_encode_s":doc_sec,"queries_encode_s":query_sec,
            "total_encode_s":round(doc_sec+query_sec,3),
            "top1":sum(r==1 for r in ranks)/len(ranks),
            "mrr":sum(1/r if r else 0 for r in ranks)/len(ranks),
            "recall_at5":sum(bool(r and r<=5) for r in ranks)/len(ranks),
            "ndcg_at5":sum(1/math.log2(r+1) if r and r<=5 else 0 for r in ranks)/len(ranks),
            "case_results":results,
            "limitations":"12 site-search queries, pure dense, model-native query instruction versus original Qwen baseline (no instruction), hardware and backend differ",
            "source_site_commit":"cf1261e"}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("SUMMARY",json.dumps({k:result[k] for k in ["top1","mrr","recall_at5","ndcg_at5","total_encode_s","dimension"]}),flush=True)
    return 0


if __name__=="__main__":raise SystemExit(main())
