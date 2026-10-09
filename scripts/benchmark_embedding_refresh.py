#!/usr/bin/env python3
"""Read-only Russian relevance evaluation on frozen existing GSC/Yandex labels.

Uses a local checkout as the retrieval corpus; does not mutate Data Platform
vectors, indices, embedding provider config, or production model services.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import math
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


class HtmlText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = []
        self.main = []
        self.head_description = ""
        self.inside_title = 0
        self.main_depth = 0
        self.skip = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.inside_title += 1
        if tag == "meta" and attrs.get("name") == "description":
            self.head_description = attrs.get("content", "")
        if tag == "main":
            self.main_depth += 1
        if self.main_depth and tag in {"script", "style", "svg", "nav", "footer", "header"}:
            self.skip.append(tag)
    def handle_endtag(self, tag):
        if tag == "title" and self.inside_title:
            self.inside_title -= 1
        if tag == "main" and self.main_depth:
            self.main_depth -= 1
        if self.skip and tag == self.skip[-1]:
            self.skip.pop()
    def handle_data(self, data):
        if self.inside_title:
            self.title.append(data)
        if self.main_depth and not self.skip:
            self.main.append(data)


def site_corpus(root):
    docs = []
    for path in sorted(root.rglob("*.html")):
        relative = path.relative_to(root).as_posix()
        parser = HtmlText()
        parser.feed(path.read_text(encoding="utf-8"))
        title = " ".join(parser.title)
        description = parser.head_description
        body = " ".join(parser.main)
        text = " ".join(f"{title}. {description}. {body}".split())[:1700]
        uri = "https://arvectum.com/" if relative == "index.html" else "https://arvectum.com/" + relative
        if text:
            docs.append(dict(uri=uri, text=text, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return docs


def fetch(url, obj, timeout=160):
    req = urllib.request.Request(url, data=json.dumps(obj,ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def encode(url, name, texts):
    start=time.monotonic()
    res=fetch(url+"/v1/embeddings",{"model":name,"input":texts})
    rows=sorted(res["data"],key=lambda d:d["index"])
    emb=[r["embedding"] for r in rows]
    if len(emb)!=len(texts) or not all(emb):
        raise RuntimeError("Embedding response count mismatch")
    elapsed=time.monotonic()-start
    return emb, elapsed


def cosine(a,b):
    dot=sum(x*y for x,y in zip(a,b))
    den=math.sqrt(sum(x*x for x in a))*math.sqrt(sum(x*x for x in b))
    return dot/den if den else -1


def evaluate(docs,cases,model,port,timeout):
    url=f"http://127.0.0.1:{port}"
    deadline=time.monotonic()+timeout
    while True:
        try:
            with urllib.request.urlopen(url+"/health",timeout=3) as resp:
                if resp.status==200: break
        except Exception:
            pass
        if time.monotonic()>deadline:raise TimeoutError(f"server {port} not healthy within {timeout}s")
        time.sleep(1)
    texts=[d["text"] for d in docs]
    # Each candidate gets the *exact same* input text and queries.
    vectors=[]
    times=[]
    for offset in range(0,len(texts),3):
        b,t=encode(url,model,texts[offset:offset+3])
        vectors.extend(b);times.append(t)
    queries=[c["query"] for c in cases]
    qvectors=[]
    for offset in range(0,len(queries),3):
        b,t=encode(url,model,queries[offset:offset+3])
        qvectors.extend(b);times.append(t)
    if len({len(v) for v in vectors+qvectors})!=1: raise ValueError("dimensional mismatch")
    scores=[]
    allr=[]
    for c,vector in zip(cases,qvectors):
        ranked=sorted(zip(docs,vectors), key=lambda item: cosine(vector,item[1]),reverse=True)
        uris=[d["uri"] for d,_ in ranked]
        expected=set(c["expected_ids"])
        r=next((i+1 for i,uri in enumerate(uris) if uri in expected),None)
        scores.append(r)
        allr.append({"id":c["id"],"expected":list(expected),"rank":r,
                     "top5":uris[:5],"top1":uris[0]})
    ndcg=sum((1/math.log2(r+1) if r and r<=5 else 0) for r in scores)/len(scores)
    return {"model":model,"dimension":len(vectors[0]),"docs":len(docs),"queries":len(queries),
            "top1":sum(r==1 for r in scores)/len(scores),
            "mrr":sum(1/r if r else 0 for r in scores)/len(scores),
            "recall_at5":sum(bool(r and r<=5) for r in scores)/len(scores),
            "ndcg_at5":ndcg,"embedding_time_s":round(sum(times),2),
            "case_results":allr}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--models-root",type=Path,default=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks"))
    ap.add_argument("--site-public",type=Path,default=Path("/Volumes/ArvectumSSD/Arvectum/repos/arvectum-site/public"))
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--model",choices=["0.6b","4b","8b"],required=True)
    ap.add_argument("--port",type=int,default=18095)
    args=ap.parse_args()
    gguf={
      "0.6b":("qwen3-embedding-0.6b-q8","Qwen3-Embedding-0.6B-Q8_0.gguf"),
      "4b":("qwen3-embedding-4b-q8","Qwen3-Embedding-4B-Q8_0.gguf"),
      "8b":("qwen3-embedding-8b-q4","Qwen3-Embedding-8B-Q4_K_M.gguf"),
    }
    sub,filename=gguf[args.model]
    file=args.models_root/sub/filename
    if not file.is_file(): raise SystemExit(f"missing: {file}")
    benchmark=Path(__file__).resolve().parents[1]/"benchmarks/growth_search_console_v1.json"
    raw=benchmark.read_bytes()
    data=json.loads(raw)
    cases=data["cases"]
    docs=site_corpus(args.site_public)
    expected=set(x for c in cases for x in c["expected_ids"])
    missing=sorted(expected-{d["uri"] for d in docs})
    if missing:raise SystemExit(f"Expected pages missing: {missing}")
    cmd=["/opt/homebrew/bin/llama-server","--model",str(file),
         "--alias",filename,"--embedding","--pooling","last",
         "--ctx-size","2048","--batch-size","512","--ubatch-size","512",
         "--parallel","1","--host","127.0.0.1","--port",str(args.port),"--no-webui"]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    proc=subprocess.Popen(cmd,stdout=(args.output.parent/f"{args.model}.server.log").open("w"),
                          stderr=subprocess.STDOUT)
    try:
        result=evaluate(docs,cases,filename,args.port,90)
        result.update({"benchmark":"growth_search_console_v1","suite_sha256":hashlib.sha256(raw).hexdigest(),
                       "site_corpus_hash":hashlib.sha256(json.dumps(docs,sort_keys=True).encode()).hexdigest(),
                       "corpus_note":"local current site checkout, 45 HTML pages, first 1700 characters of main/title/description",
                       "engine":"llama.cpp","format":"GGUF","model_file":str(file),
                       "time_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())})
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps({k:result[k] for k in ["model","dimension","docs","queries","top1","mrr","recall_at5","ndcg_at5","embedding_time_s"]},ensure_ascii=False),flush=True)
    finally:
        proc.terminate()
        try:proc.wait(timeout=12)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()


if __name__=="__main__":
    main()
