#!/usr/bin/env python3
"""OCR quality on public_v2 human-reviewed Russian PDF scans.

No production API or models modified. Runs a local Qwen3-VL GGUF server on a
separate loopback port and compares against the same classical OCR baseline.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def distance(a,b):
    if len(a)<len(b): a,b=b,a
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        nxt=[i]
        for j,y in enumerate(b,1):
            nxt.append(min(nxt[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=nxt
    return prev[-1]


def normalize(s):
    s=re.sub(r"\[Page\s+\d+\]\s*"," ",s)
    s=re.sub(r"\`\`\`(?:text)?"," ",s)
    return " ".join(s.replace("\u00a0"," ").split())


def score(ref,output,required):
    ref=normalize(ref)
    out=normalize(output)
    return {"cer":round(distance(ref,out)/max(len(ref),1),6),
            "wer":round(distance(ref.split(),out.split())/max(len(ref.split()),1),6),
            "required_text_passed":all(normalize(x) in out for x in required),
            "output_chars":len(out),"gold_chars":len(ref)}


def oai_chat(port,image,prompt):
    img="data:image/png;base64,"+base64.b64encode(image.read_bytes()).decode()
    body={"model":"qwen3-vl-4b-benchmark","messages":[{"role":"user","content":[
           {"type":"text","text":prompt},{"type":"image_url","image_url":{"url":img}}]}],
           "temperature":0,"max_tokens":3000,"stream":False}
    req=urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=280) as res:
        answer=json.loads(res.read())
    return answer["choices"][0]["message"]["content"],answer.get("usage",{})


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--manifest",type=Path,default=Path(__file__).resolve().parents[1]/"benchmarks/corpora/public_v2/manifest.json")
    a.add_argument("--model-root",type=Path,default=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks/qwen3-vl-4b-gguf"))
    a.add_argument("--output",type=Path,required=True)
    a.add_argument("--port",type=int,default=18097)
    args=a.parse_args()
    base=args.manifest.parent
    raw=args.manifest.read_bytes()
    data=json.loads(raw)
    cases=[c for c in data["artifacts"] if c.get("ocr_required") and c.get("gold_text_file")]
    assert len(cases)==2,"expected frozen two-scan public_v2 human gold"
    model=args.model_root/"Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    mmproj=args.model_root/"mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
    assert model.is_file() and mmproj.is_file()
    aout=args.output.parent
    aout.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dp-ocr-refresh-", dir=aout) as temp:
        tmp=Path(temp)
        imgs={}
        refs={}
        for c in cases:
            pdffile=base/c["file"]
            assert hashlib.sha256(pdffile.read_bytes()).hexdigest()==c["sha256"]
            gold=base/c["gold_text_file"]
            assert hashlib.sha256(gold.read_bytes()).hexdigest()==c["gold_sha256"]
            prefix=tmp/c["id"]
            subprocess.run(["pdfimages","-png",str(pdffile),str(prefix)],check=True,
                stdout=subprocess.DEVNULL)
            pngs=sorted(tmp.glob(c["id"]+"-*.png"))
            if not pngs:raise RuntimeError("no image extracted for "+c["id"])
            imgs[c["id"]]=pngs[0]; refs[c["id"]]=gold.read_text(encoding="utf-8")
        results={"suite":"public_v2_human_reviewed_scans","suite_sha256":hashlib.sha256(raw).hexdigest(),
                 "model":"Qwen3VL-4B-Instruct-Q4_K_M.gguf","backend":"llama.cpp",
                 "policy":"candidate-only-no-production-change","cases":[]}
        for c in cases:
            started=time.perf_counter()
            rawtext=subprocess.check_output(["tesseract",str(imgs[c["id"]]),"stdout","-l","rus+eng","--psm","3"],stderr=subprocess.DEVNULL).decode()
            baseline={"model":"Tesseract rus+eng","latency_s":round(time.perf_counter()-started,3),
                      **score(refs[c["id"]],rawtext,c["required_text"])}
            results["cases"].append({"id":c["id"],"tesseract":baseline})
            print("TESSERACT",c["id"],baseline,flush=True)
        cmd=["/opt/homebrew/bin/llama-server","--model",str(model),"--mmproj",str(mmproj),
             "--alias","qwen3-vl-4b-benchmark","--host","127.0.0.1","--port",str(args.port),
             "--ctx-size","8192","--batch-size","512","--parallel","1","--no-webui"]
        with (aout/"ocr-qwen3-vl-server.log").open("w") as serverlog:
            proc=subprocess.Popen(cmd,stdout=serverlog,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+90
                while True:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health",timeout=3) as r:
                            if r.status==200:break
                    except Exception:pass
                    if time.monotonic()>deadline:raise TimeoutError("VLM failed to start")
                    time.sleep(1)
                prompt=("Перепиши весь видимый текст с изображения документа на русском языке максимально точно, "
                        "сохрани исходный порядок чтения, таблицы, числовые значения, даты, номера и поля форм. "
                        "Не добавляй объяснений, резюме или вымышленных данных. Выведи только распознанный текст.")
                for c,res in zip(cases,results["cases"]):
                    started=time.perf_counter()
                    output,usage=oai_chat(args.port,imgs[c["id"]],prompt)
                    res["qwen3vl"]={"model":results["model"],"latency_s":round(time.perf_counter()-started,3),
                                    **score(refs[c["id"]],output,c["required_text"]),"usage":usage}
                    (aout/("ocr-"+c["id"]+".txt")).write_text(output)
                    print("QWEN3VL",c["id"],res["qwen3vl"],flush=True)
                    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
            finally:
                proc.terminate()
                try:proc.wait(timeout=12)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
        results["summary"]={}
        for name in ["tesseract","qwen3vl"]:
            rs=[r[name] for r in results["cases"] if name in r]
            results["summary"][name]={
                "cases":len(rs),"mean_cer":sum(x["cer"] for x in rs)/len(rs),
                "mean_wer":sum(x["wer"] for x in rs)/len(rs),
                "mean_latency_s":sum(x["latency_s"] for x in rs)/len(rs),
                "required_text_pass_rate":sum(x["required_text_passed"] for x in rs)/len(rs)}
        args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
        print("SUMMARY",json.dumps(results["summary"],ensure_ascii=False),flush=True)


if __name__=="__main__":main()
