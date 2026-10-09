#!/usr/bin/env python3
"""Independent dense Russian retrieval smoke for BGE-M3, read-only."""
from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,time,math
import numpy as np
from benchmark_embedding_refresh import site_corpus

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--output",type=Path,required=True)
 p.add_argument("--model",type=Path,default=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks/bge-m3"))
 p.add_argument("--device",default="mps")
 a=p.parse_args()
 repo=Path(__file__).resolve().parents[1]
 suite=repo/"benchmarks/growth_search_console_v1.json"
 raw=suite.read_bytes()
 cases=json.loads(raw)["cases"]
 docs=site_corpus(Path("/Volumes/ArvectumSSD/Arvectum/repos/arvectum-site/public"))
 ref=json.loads((repo/"benchmarks/results/model_refresh_2026-10-09/embedding-4b.json").read_text())
 h=hashlib.sha256(json.dumps(docs,sort_keys=True).encode()).hexdigest()
 assert h==ref["site_corpus_hash"] and ref["suite_sha256"]==hashlib.sha256(raw).hexdigest()
 from sentence_transformers import SentenceTransformer
 print("LOAD",a.model,a.device,flush=True)
 start=time.perf_counter()
 model=SentenceTransformer(str(a.model),device=a.device,local_files_only=True,trust_remote_code=False)
 loaded=round(time.perf_counter()-start,3)
 start=time.perf_counter()
 dv=model.encode([d["text"] for d in docs],batch_size=2,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
 doc_time=round(time.perf_counter()-start,3)
 start=time.perf_counter()
 qv=model.encode([c["query"] for c in cases],batch_size=2,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
 q_time=round(time.perf_counter()-start,3)
 scores=np.asarray(qv)@np.asarray(dv).T
 rows=[]
 for c,row in zip(cases,scores):
  order=np.argsort(-row)
  top=[docs[int(i)]["uri"] for i in order]
  rank=next((i+1 for i,uri in enumerate(top) if uri in c["expected_ids"]),None)
  rows.append({"id":c["id"],"rank":rank,"top5":top[:5],"top1":top[0],"expected":c["expected_ids"]})
  print("CASE",c["id"],rank,flush=True)
 ranks=[r["rank"] for r in rows]
 obj={"model":"BAAI/bge-m3","format":"original-pytorch","engine":"sentence-transformers","device":a.device,
 "docs":len(docs),"queries":len(cases),"dimension":int(dv.shape[1]),"site_corpus_hash":h,
 "suite_sha256":hashlib.sha256(raw).hexdigest(),"suite":"growth_search_console_v1",
 "top1":sum(r==1 for r in ranks)/len(ranks),
 "mrr":sum(1/r if r else 0 for r in ranks)/len(ranks),
 "recall_at5":sum(r is not None and r<=5 for r in ranks)/len(ranks),
 "ndcg_at5":sum(1/math.log2(r+1) if r and r<=5 else 0 for r in ranks)/len(ranks),
 "load_s":loaded,"documents_encode_s":doc_time,"queries_encode_s":q_time,
 "total_encode_s":round(doc_time+q_time,3),"case_results":rows,
 "limitations":"dense-only BGE; sparse and ColBERT heads are not tested; test set 12 cases; time is not same backend as Qwen GGUF."}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")
 print("RESULT",json.dumps({k:obj[k] for k in ["dimension","top1","mrr","recall_at5","ndcg_at5","total_encode_s","load_s"]}),flush=True)

if __name__=="__main__":main()
