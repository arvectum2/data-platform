#!/usr/bin/env python3
"""Isolated GGUF GigaChat 3.1 Lightning: 5 Russian source-grounded-answer smokes.

Only benchmark loopback port, no production model/service/index changes.
Compares lexical term/citation/abstention checks with Qwen3.5-4B/9B MLX
on the exact same frozen faithfulness_real_v1 sources; NOT official score.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, time, urllib.request, urllib.error
from pathlib import Path

MODEL=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks/russian-models/gigachat-3.1-lightning-q4/GigaChat3.1-10B-A1.8B-q4_K_M.gguf")


def chat(port, alias, system, user):
    data={"model":alias,"messages":[{"role":"system","content":system},
         {"role":"user","content":user}],"temperature":0,"max_tokens":320}
    req=urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
         data=json.dumps(data,ensure_ascii=False).encode("utf-8"),
         headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=150) as f:
        resp=json.load(f)
    return resp["choices"][0]["message"]["content"],resp.get("usage",{})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--model",type=Path,default=MODEL)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--port",type=int,default=18099)
    a=parser.parse_args()
    assert a.model.is_file() and a.model.stat().st_size>6_000_000_000,"Verified GGUF missing"
    src=Path(__file__).resolve().parents[1]/"benchmarks/faithfulness_real_v1.json"
    raw=src.read_bytes(); cases=json.loads(raw)["cases"]
    alias="gigachat31-lightning-local"
    cmd=["/opt/homebrew/bin/llama-server","--model",str(a.model),"--alias",alias,
         "--host","127.0.0.1","--port",str(a.port),"--ctx-size","8192",
         "--parallel","1","--batch-size","512","--n-gpu-layers","99","--no-webui"]
    a.output.parent.mkdir(parents=True,exist_ok=True)
    t0=time.monotonic()
    with (a.output.parent/"gigachat31.server.log").open("w") as log:
        proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(110):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/health",timeout=2) as response:
                        if response.status==200:break
                except Exception:pass
                if proc.poll() is not None:raise RuntimeError(f"Model server exited {proc.returncode}")
                time.sleep(1)
            else:raise TimeoutError("GigaChat GGUF server start timed out")
            load_sec=round(time.monotonic()-t0,3)
            print("MODEL_LOADED",load_sec,flush=True)
            results=[]
            for c in cases:
                blocks="\n".join("[{}] {}".format(e["chunk_id"],e["text"]) for e in c["evidence"])
                system=("Ты анализируешь только предоставленные фрагменты документов. "
                        "Нельзя добавлять факты вне этих фрагментов. Если данных недостаточно, "
                        "напиши строго: 'Недостаточно данных в источниках.' "
                        "В остальных случаях дай краткий ответ на русском, затем отдельной строкой "
                        "'Источники: [ID]' для каждого использованного фрагмента. "
                        "Ответ должен содержать точные номера, суммы и названия без изменения.")
                user="Вопрос: "+c["query"]+"\nИсточники:\n"+blocks+"\nОтветь без рассуждений."
                t=time.monotonic()
                answer,usage=chat(a.port,alias,system,user)
                sec=round(time.monotonic()-t,3)
                clean=re.sub(r"<think>.*?</think>","",answer,flags=re.DOTALL).strip()
                clean=re.sub(r"^.*?</think>","",clean,flags=re.DOTALL).strip()
                required=c.get("required_answer_terms") or []
                present=[term for term in required if term.casefold() in clean.casefold()]
                ids=sorted(set(x for claim in c.get("required_claims",[]) for x in claim["expected_chunk_ids"]))
                if not ids:ids=[e["chunk_id"] for e in c["evidence"]]
                citations=[e for e in ids if ("["+e+"]") in clean]
                abstained=bool(re.search(r"недостаточно данных|не указан|не указано|нет данных|отсутствует",clean,re.I))
                false_bik=bool(re.search(r"(?<!\d)\d{9}(?!\d)",clean)) if c["expected_abstained"] else False
                result={"id":c["id"],"expected_abstained":c["expected_abstained"],
                        "detected_abstention":abstained,"suspicious_bik":false_bik,
                        "terms_pass":len(present)==len(required),
                        "citation_pass":(len(citations)==len(ids)) if not c["expected_abstained"] else True,
                        "abstention_pass":(abstained and not false_bik) if c["expected_abstained"] else not abstained,
                        "time_s":sec,"answer":clean[:1800],"usage":usage}
                results.append(result)
                print("CASE",result["id"],"terms",result["terms_pass"],
                      "citations",result["citation_pass"],"abstain",result["abstention_pass"],"seconds",sec,flush=True)
            obj={"model":"ai-sage/GigaChat3.1-10B-A1.8B-GGUF","revision":"97045b260251cfa86f5ad25638fa2dd074153446",
                 "quantization":"Q4_K_M","engine":"llama.cpp","port":a.port,
                 "load_s":load_sec,"suite":"faithfulness_real_v1",
                 "suite_sha256":hashlib.sha256(raw).hexdigest(),"cases":results,
                 "method":"Exploratory lexical/structural checks with same system/user content as Qwen3.5 MLX smoke, not production Gemma claim-support suite",
                 "summary":{"cases":len(results),
                  "terms_pass":sum(r["terms_pass"] for r in results)/len(results),
                  "citations_pass":sum(r["citation_pass"] for r in results)/len(results),
                  "abstention_pass":sum(r["abstention_pass"] for r in results)/len(results),
                  "combined_pass":sum(r["terms_pass"] and r["citation_pass"] and r["abstention_pass"] for r in results)/len(results),
                  "mean_time_s":sum(r["time_s"] for r in results)/len(results)}}
            a.output.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")
            print("SUMMARY",json.dumps(obj["summary"]),flush=True)
        finally:
            proc.terminate()
            try:proc.wait(timeout=12)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()


if __name__=="__main__":main()
