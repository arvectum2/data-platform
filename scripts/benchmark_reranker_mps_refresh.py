#!/usr/bin/env python3
"""Qwen3 rerankers on Metal against fixed Qwen3-4B dense top-five candidates."""
from __future__ import annotations
import argparse,hashlib,json,math,statistics,time
from pathlib import Path
from benchmark_embedding_refresh import site_corpus
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--model",choices=["0.6b","4b"],required=True)
 p.add_argument("--device",choices=["mps","cpu"],default="mps")
 p.add_argument("--output",type=Path,required=True)
 a=p.parse_args()
 root=Path(__file__).resolve().parents[1]
 model=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks")/("qwen3-reranker-"+a.model)
 dense=json.loads((root/"benchmarks/results/model_refresh_2026-10-09/embedding-4b.json").read_text())
 suitefile=root/"benchmarks/growth_search_console_v1.json"
 suite=json.loads(suitefile.read_text())["cases"]
 assert dense["suite_sha256"]==hashlib.sha256(suitefile.read_bytes()).hexdigest()
 docs={x["uri"]:x["text"] for x in site_corpus(Path("/Volumes/ArvectumSSD/Arvectum/repos/arvectum-site/public"))}
 from sentence_transformers import CrossEncoder
 import torch
 torch.set_num_threads(4)
 if a.device=="mps":torch.mps.set_per_process_memory_fraction(0.55)
 print("LOADING",model,a.device,flush=True)
 start=time.perf_counter()
 obj=CrossEncoder(str(model),device=a.device,local_files_only=True,
                  max_length=768,model_kwargs={"dtype":torch.bfloat16})
 loaded=round(time.perf_counter()-start,3)
 print("LOADED",loaded,flush=True)
 byid={c["id"]:c for c in dense["case_results"]}
 results=[]
 for c in suite:
  top=byid[c["id"]]["top5"]
  pairs=[(c["query"],docs[u][:800]) for u in top]
  start=time.perf_counter()
  predictions=obj.predict(pairs,batch_size=1,show_progress_bar=False)
  elapsed=round(time.perf_counter()-start,3)
  scores=[float(z) for z in predictions]
  urls=[top[i] for i in sorted(range(len(top)),key=lambda i:scores[i],reverse=True)]
  rank=next((i+1 for i,u in enumerate(urls) if u in c["expected_ids"]),None)
  results.append({"id":c["id"],"rank":rank,"seconds":elapsed,"top5":urls})
  print("CASE",c["id"],rank,elapsed,flush=True)
 ranks=[r["rank"] for r in results]
 out={"model":str(model),"device":a.device,"dtype":"bfloat16",
 "suite":"growth_search_console_v1","suite_sha256":hashlib.sha256(suitefile.read_bytes()).hexdigest(),
 "candidate_source":"Qwen3-Embedding-4B top5","candidate_chars":800,
 "load_s":loaded,"cases":results,"summary":{"top1":sum(x==1 for x in ranks)/len(ranks),
 "mrr":sum(1/r if r else 0 for r in ranks)/len(ranks),
 "ndcg_at5":sum(1/math.log2(r+1) if r else 0 for r in ranks)/len(ranks),
 "recall_at5":sum(r is not None for r in ranks)/len(ranks),
 "p50_s":round(statistics.median(r["seconds"] for r in results),3)}}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
 print("RESULT",json.dumps(out["summary"]),flush=True)
if __name__=="__main__":main()
