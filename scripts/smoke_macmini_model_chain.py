#!/usr/bin/env python3
"""Read-only model-chain E2E smoke: local PDF/DOCX/scanned-PDF -> embed -> rerank -> cited LLM.

Not a full Data Platform DB/API ingestion test: no persistent writes or updates.
Runs only on the committed public_v2 procurement fixtures.
"""
from __future__ import annotations
import json,re,subprocess,time,urllib.request,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"benchmarks/corpora/public_v2/fixtures"
OUT=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results/macmini-model-chain.json")
def post(url,body):
 req=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
                            headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)
def docx_read(path):
 with zipfile.ZipFile(path) as z:xml=z.read("word/document.xml")
 root=ET.fromstring(xml)
 t="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
 p="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
 return "\n".join("".join(n.text or "" for n in item.iter(t)) for item in root.iter(p))
def pdf_read(path):
 return subprocess.check_output(["pdftotext","-layout",str(path),"-"]).decode("utf-8")
def scan_read(path,store):
 prefix=store/"scan"
 subprocess.run(["pdfimages","-png",str(path),str(prefix)],check=True,stdout=subprocess.DEVNULL)
 imgs=sorted(store.glob("scan-*.png"))
 assert imgs
 return subprocess.check_output(["tesseract",str(imgs[0]),"stdout","-l","rus+eng","--psm","3"],stderr=subprocess.DEVNULL).decode()
def main():
 tmp=OUT.parent/"model-chain-input";tmp.mkdir(parents=True,exist_ok=True)
 tic=time.perf_counter()
 src=[
  ("native-control-pdf",pdf_read(BASE/"procurement_control_notice.pdf")),
  ("docx-nmck",docx_read(BASE/"procurement_nmck.docx")),
  ("scanned-control-pdf",scan_read(BASE/"procurement_control_notice_scan.pdf",tmp))]
 documents=[{"id":n,"text":s[:5000]} for n,s in src]
 parse_s=round(time.perf_counter()-tic,3)
 assert len(documents)==3 and all(len(c["text"])>200 for c in documents)
 query="Какой орган контроля указан в документе и какой код формы по ОКУД?"
 alias="Qwen3-Embedding-4B"
 t=time.perf_counter()
 embs=post("http://127.0.0.1:8090/v1/embeddings",
 {"model":alias,"input":[query]+[x["text"] for x in documents]})["data"]
 embs=sorted(embs,key=lambda x:x["index"])
 from math import sqrt
 def cos(a,b):
  return sum(x*y for x,y in zip(a,b))/(sqrt(sum(x*x for x in a))*sqrt(sum(y*y for y in b)))
 ranking=sorted(zip(documents,embs[1:]),key=lambda pair:cos(embs[0]["embedding"],pair[1]["embedding"]),reverse=True)
 dense_top=[d["id"] for d,_ in ranking]
 embed_s=round(time.perf_counter()-t,3)
 t=time.perf_counter()
 top=[d for d,_ in ranking]
 bge=post("http://127.0.0.1:8091/score",{"model":"BAAI/bge-reranker-v2-m3",
 "pairs":[[query,d["text"][:800]] for d in top]})["scores"]
 selected=sorted(zip(top,bge),key=lambda pair:pair[1],reverse=True)
 rerank_s=round(time.perf_counter()-t,3)
 evidence=[{"id":d["id"],"text":d["text"][:1400]} for d,_ in selected[:2]]
 evidence_str="\n".join(f'[{c["id"]}] {c["text"]}' for c in evidence)
 model="arvectum-gemma4-12b-it-qat-q4_0"
 messages=[{"role":"system","content":"Отвечай только по данным источников. Сохраняй названия и номера точно; сослаться на ID источника в квадратных скобках. Если данных недостаточно, сообщи об этом."},
 {"role":"user","content":"Вопрос: "+query+"\nИсточники:\n"+evidence_str+"\nДай короткий ответ."}]
 t=time.perf_counter()
 ans=post("http://127.0.0.1:8081/v1/chat/completions",
          {"model":model,"messages":messages,"temperature":0,"max_tokens":200})
 answer=ans["choices"][0]["message"]["content"]
 gen_s=round(time.perf_counter()-t,3)
 checks={"source_retrieved":any(x["id"]=="native-control-pdf" for x in evidence),
         "name_present":"Комитет финансов Санкт-Петербурга" in answer,
         "okud_present":"0506135" in answer,
         "citation_present":any(x["id"] in {n.strip() for b in re.findall(r"\\[([^\\]]+)\\]",answer) for n in b.split(",")} for x in evidence)}
 result={"pipeline":"public PDF native + DOCX XML + scanned PDF Tesseract -> Qwen 4B vector -> BGE rerank -> Gemma cited answer",
         "durable_production_writes":False,"model_chain_only":True,
         "files":len(documents),"query":query,"dense_order":dense_top,
         "rerank_order":[d["id"] for d,s in selected],"answer":answer,
         "checks":checks,"all_passed":all(checks.values()),
         "latency_s":{"extract":parse_s,"embedding":embed_s,"rerank":rerank_s,"generation":gen_s,
                      "total":round(parse_s+embed_s+rerank_s+gen_s,3)}}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
 print("RESULT",json.dumps({k:result[k] for k in ["checks","latency_s","dense_order","rerank_order","all_passed"]},ensure_ascii=False),flush=True)
 if not result["all_passed"]:raise SystemExit(1)
if __name__=="__main__":main()
