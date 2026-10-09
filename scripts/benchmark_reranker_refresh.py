#!/usr/bin/env python3
"""Local-only reranking quality study on frozen GSC labels and exact dense top-5.

No writes to live Data Platform, no changes to rerank defaults or indices.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import statistics
import time
import urllib.request
from pathlib import Path
from benchmark_embedding_refresh import site_corpus


def bge_score(query,docs):
    body={"model":"BAAI/bge-reranker-v2-m3","pairs":[[query,d[:800]] for d in docs]}
    req=urllib.request.Request("http://127.0.0.1:8091/score",
              data=json.dumps(body,ensure_ascii=False).encode(),
              headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=40) as response:
        result=json.load(response)
    if len(result["scores"])!=len(docs):raise RuntimeError("BGE score count mismatch")
    return [float(x) for x in result["scores"]]


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--dense-results",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    a.add_argument("--site-public",type=Path,default=Path("/Volumes/ArvectumSSD/Arvectum/repos/arvectum-site/public"))
    a.add_argument("--rerank-model",default="/Volumes/ArvectumSSD/Models/data-platform-benchmarks/qwen3-reranker-0.6b")
    args=a.parse_args()
    suitefile=Path(__file__).resolve().parents[1]/"benchmarks/growth_search_console_v1.json"
    suite=json.loads(suitefile.read_text())
    dense=json.loads(args.dense_results.read_text())
    assert dense["suite_sha256"]==hashlib.sha256(suitefile.read_bytes()).hexdigest()
    docs={x["uri"]:x["text"] for x in site_corpus(args.site_public)}
    cases={c["id"]:c for c in suite["cases"]}
    dense_cases={c["id"]:c for c in dense["case_results"]}
    from sentence_transformers import CrossEncoder
    t_load=time.perf_counter()
    model=CrossEncoder(args.rerank_model,max_length=768,device="cpu")
    load_s=time.perf_counter()-t_load
    results=[]
    for c in suite["cases"]:
        base=dense_cases[c["id"]]
        candidates=base["top5"]
        pairs=[(c["query"],docs[uri][:800]) for uri in candidates]
        original=candidates.index(next((x for x in candidates if x in c["expected_ids"]), None))+1 if any(x in c["expected_ids"] for x in candidates) else None
        started=time.perf_counter()
        bges=bge_score(c["query"],[p[1] for p in pairs])
        bge_s=time.perf_counter()-started
        started=time.perf_counter()
        scores=[float(x) for x in model.predict(pairs,batch_size=1,show_progress_bar=False)]
        qwen_s=time.perf_counter()-started
        bge_order=[candidates[i] for i in sorted(range(len(candidates)),key=lambda i:bges[i],reverse=True)]
        qwen_order=[candidates[i] for i in sorted(range(len(candidates)),key=lambda i:scores[i],reverse=True)]
        def rank(items):
            return next((i+1 for i,x in enumerate(items) if x in c["expected_ids"]),None)
        results.append({"id":c["id"],"original_rank":original,
                        "bge_rank":rank(bge_order),"qwen_rank":rank(qwen_order),
                        "bge_s":round(bge_s,3),"qwen_s":round(qwen_s,3),
                        "original_top5":candidates,
                        "bge_top5":bge_order,"qwen_top5":qwen_order})
        print(c["id"],"base",original,"BGE",rank(bge_order),"Qwen",rank(qwen_order),flush=True)
    summary={}
    for n,key,timekey in [("dense_baseline","original_rank",None),
                          ("bge_v2_m3","bge_rank","bge_s"),
                          ("qwen3_reranker_0.6b","qwen_rank","qwen_s")]:
        ranks=[r[key] for r in results]
        summary[n]={"top1":sum(x==1 for x in ranks)/len(ranks),
                    "mrr":sum(1/x if x else 0 for x in ranks)/len(ranks),
                    "recall_at5":sum(x is not None for x in ranks)/len(ranks),
                    "ndcg_at5":sum(1/math.log2(x+1) if x else 0 for x in ranks)/len(ranks)}
        if timekey:summary[n]["p50_s"]=round(statistics.median(r[timekey] for r in results),3)
    out={"suite":"growth_search_console_v1","suite_sha256":hashlib.sha256(suitefile.read_bytes()).hexdigest(),
         "dense_reference":str(args.dense_results),"models":["BAAI/bge-reranker-v2-m3",args.rerank_model],
         "candidate_limit":5,"max_chars":800,"cpu_qwen":True,"qwen_load_s":round(load_s,2),
         "notes":"Different candidate source from accepted production hybrid rerank gate; comparisons are within this fixed dense top-5 only, cannot recover rank>5.",
         "summary":summary,"cases":results}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print("SUMMARY",json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":main()
