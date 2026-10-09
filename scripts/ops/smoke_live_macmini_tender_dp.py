#!/usr/bin/env python3
"""Bounded LIVE production-stack E2E using only frozen PUBLIC procurement fixtures.

Ephemeral, uniquely named private test collection. Never edits existing collections.
Test collection is deleted in finally, result redacts all auth values.
Run only with ARVECTUM_DATA_INTERNAL_API_KEY sourced from the local runtime.
"""
from __future__ import annotations
import json,os,time,uuid,statistics
from pathlib import Path
import httpx

BASE=os.environ.get("ARVECTUM_STACK_SMOKE_URL","http://127.0.0.1:8094")
ROOT=Path(__file__).resolve().parents[2]
FIXTURES=ROOT/"benchmarks/corpora/public_v2/fixtures"
OUTPUT=Path(os.environ.get("ARVECTUM_STACK_SMOKE_OUTPUT","/Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results/macmini-live-e2e.json"))

def require(condition,why):
 if not condition:raise AssertionError(why)
def main():
 key=os.getenv("ARVECTUM_DATA_INTERNAL_API_KEY","")
 require(len(key)>8,"The runtime API key was not provided via env")
 code=uuid.uuid4().hex[:10]
 collection="macmini-acceptance-"+code
 result={"type":"production_api_isolated_collection_live_smoke",
         "collection_prefix":"macmini-acceptance-",
         "cleanup_verified":False,"production_model_changes":False,
         "customer_collections_touched":False,"steps":[], "models":{}}
 start_all=time.perf_counter()
 client=httpx.Client(base_url=BASE,headers={"X-Arvectum-Key":key},trust_env=False,timeout=100)
 created=False
 def step(name,fn):
  started=time.perf_counter()
  try:
   obj=fn()
   sec=round(time.perf_counter()-started,3)
   result["steps"].append({"stage":name,"ok":True,"seconds":sec})
   print("PASS",name,sec,flush=True)
   return obj
  except Exception as e:
   sec=round(time.perf_counter()-started,3)
   result["steps"].append({"stage":name,"ok":False,"seconds":sec,
                           "error_type":type(e).__name__,"detail":str(e)[:350]})
   print("FAIL",name,type(e).__name__,str(e)[:250],flush=True)
   raise
 def post_json(path,body):
  r=client.post(path,json=body)
  r.raise_for_status()
  return r.json()
 try:
  st=step("authenticated_status",lambda:client.get("/v1/status").raise_for_status().json())
  require(st["embedding_dimension"]==2560,"Live vector dimensions unexpectedly changed")
  result["models"]={"embedding":st.get("embedding_model"),"dim":st.get("embedding_dimension"),
                   "ocr":st.get("ocr_provider"),"environment":st.get("environment")}
  def make_collection():
   x=post_json("/v1/collections",{"collection_id":collection,"owner":"model-acceptance",
      "name":"Macmini Model Acceptance Public Fixtures","default_language":"ru"})
   require(x["collection_id"]==collection,"Mismatched new collection ID")
   return x
  step("create_isolated_collection",make_collection)
  created=True
  files=[
   ("control-notice","procurement_control_notice.pdf","application/pdf"),
   ("nmck-table","procurement_nmck.docx","application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
   ("scan-control","procurement_control_notice_scan.pdf","application/pdf")]
  results=[]
  for tag,fn,mime in files:
   def ingest(tag=tag,fn=fn,mime=mime):
    with (FIXTURES/fn).open("rb") as f:
     resp=client.post("/v1/ingest/document",
        data={"collection_id":collection,"canonical_uri":f"dp-smoke://{collection}/{tag}","title":tag},
        files={"file":(fn,f,mime)})
    if resp.status_code>=400:
     raise RuntimeError(f"ingest HTTP {resp.status_code}: {resp.text[:180]}")
    payload=resp.json()
    require(payload.get("embeddings",0)>0,tag+" did not produce embeddings")
    return {"tag":tag,"chunks":payload.get("chunks"),"embeddings":payload.get("embeddings"),
      "written":payload.get("embeddings_written"),"uri":payload.get("canonical_uri")}
   results.append(step("ingest_"+tag,ingest))
  result["ingestion"]=results
  stats=step("persistent_collection_stats",lambda:client.get(f"/v1/collections/{collection}/stats").raise_for_status().json())
  result["collection_stats"]={k:stats.get(k) for k in ("resources","documents","chunks","embeddings")}
  require(stats["documents"]>=3 and stats["embeddings"]>=3,"Persisted index missing documents")
  queries=[
   ("control","Какой орган контроля указан в документе и какой код формы по ОКУД?","control-notice"),
   ("nmck","Какова НМЦК книгоиздательской продукции?","nmck-table")]
  search_rows=[]
  for label,query,expected in queries:
   def search(query=query):
    return post_json("/v1/search",{"query":query,"collections":[collection],
         "mode":"hybrid","limit":5,"rerank":True,
         "rerank_candidates":6,"rerank_strategy":"cross_encoder"})
   sr=step("hybrid_reranked_search_"+label,search)
   hits=sr.get("hits",[])
   require(hits and len(hits)>0,"No hits")
   uris=[x.get("canonical_uri","") for x in hits]
   require(any(expected in u for u in uris),"Expected public source absent")
   search_rows.append({"case":label,"query":query,"hits":len(hits),
    "expected_source_rank":next((i+1 for i,u in enumerate(uris) if expected in u),None),
    "rerank_score_observed":any(x.get("scores",{}).get("rerank") is not None for x in hits),
    "source_ids_present":all(bool(x.get("chunk_id")) for x in hits)})
  result["search"]=search_rows
  def answer():
   return post_json("/v1/answer",{"query":queries[0][1],"collections":[collection],
                      "mode":"hybrid","rerank":True,"evidence_limit":5})
  ar=step("source_grounded_answer",answer)
  ans=ar.get("answer") or ""
  result["answer"]={"abstained":ar.get("abstained"),
    "mentions_exact_control_authority":"Комитет финансов Санкт-Петербурга" in ans,
    "mentions_okud":"0506135" in ans,
    "claims":len(ar.get("claims") or []),
    "evidence_count":len(ar.get("evidence") or []),
    "source_citation_count":sum(len(x.get("chunk_ids") or []) for x in (ar.get("claims") or [])),
    "response_preview":ans[:600]}
  require(result["answer"]["mentions_okud"],"Answer lost required OKUD")
  require(result["answer"]["mentions_exact_control_authority"],"Answer lost exact control authority")
  result["inference_checks_passed"]=True
 except Exception as e:
  result["failure"]={"type":type(e).__name__,"detail":str(e)[:320]}
 finally:
  if created:
   try:
    resp=client.delete(f"/v1/collections/{collection}",params={"confirm":"true"})
    require(resp.status_code in (200,204),f"cleanup returned HTTP {resp.status_code}")
    verify=client.get(f"/v1/collections/{collection}")
    require(verify.status_code==404,"Temporary test collection still exists")
    result["cleanup_verified"]=True
    print("PASS cleanup_verified",flush=True)
   except Exception as e:
    result["cleanup_error"]={"type":type(e).__name__,"detail":str(e)[:280]}
    print("FAIL cleanup",type(e).__name__,str(e)[:200],flush=True)
  result["total_seconds"]=round(time.perf_counter()-start_all,3)
  result["passed"]=bool(result.get("inference_checks_passed") and result["cleanup_verified"])
  OUTPUT.parent.mkdir(parents=True,exist_ok=True)
  OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
  client.close()
  print("SUMMARY",json.dumps({"passed":result["passed"],"cleanup":result["cleanup_verified"],
     "total_seconds":result["total_seconds"],"models":result["models"]},ensure_ascii=False),flush=True)
 if not result["passed"]:raise SystemExit(2)
if __name__=="__main__":main()
