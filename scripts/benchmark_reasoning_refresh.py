#!/usr/bin/env python3
"""Exploratory grounded Russian Q&A candidate benchmark (not production acceptance).

Preserves frozen faithfulness_real_v1 questions/evidence; conservative automated
term/citation/abstention checks. Separate from the accepted Gemma harness.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--model",choices=["4b","9b"],required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    suite=Path(__file__).resolve().parents[1]/"benchmarks/faithfulness_real_v1.json"
    frozen=suite.read_bytes()
    cases=json.loads(frozen)["cases"]
    path=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks")/("qwen3.5-"+args.model+"-mlx-4bit")
    import mlx_lm
    from mlx_lm import load,generate
    print("LOADING",args.model,flush=True)
    loading=time.perf_counter()
    model,tokenizer=load(str(path))
    loaded=round(time.perf_counter()-loading,2)
    print("LOADED",loaded,flush=True)
    results=[]
    for case in cases:
        blocks="\n".join("[{}] {}".format(item["chunk_id"],item["text"]) for item in case["evidence"])
        sys=("Ты анализируешь только предоставленные фрагменты документов. "
             "Нельзя добавлять факты вне этих фрагментов. Если данных недостаточно, "
             "напиши строго: 'Недостаточно данных в источниках.' "
             "В остальных случаях дай краткий ответ на русском, затем отдельной строкой "
             "'Источники: [ID]' для каждого использованного фрагмента. "
             "Ответ должен содержать точные номера, суммы и названия без изменения.")
        user="Вопрос: "+case["query"]+"\nИсточники:\n"+blocks+"\nОтветь без рассуждений."
        messages=[{"role":"system","content":sys},{"role":"user","content":user}]
        try:
            prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
        except TypeError:
            prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
        started=time.perf_counter()
        raw=generate(model,tokenizer,prompt=prompt,max_tokens=400,verbose=False)
        sec=round(time.perf_counter()-started,3)
        clean=re.sub(r"<think>.*?</think>","",raw,flags=re.DOTALL).strip()
        clean=re.sub(r"^.*?</think>","",clean,flags=re.DOTALL).strip()
        required=case.get("required_answer_terms") or []
        present=[term for term in required if term.casefold() in clean.casefold()]
        expected_ids=sorted(set(id for claim in case.get("required_claims",[]) for id in claim["expected_chunk_ids"]))
        if not expected_ids:expected_ids=[e["chunk_id"] for e in case["evidence"]]
        citations=[e for e in expected_ids if ("["+e+"]") in clean]
        abstain=bool(re.search(r"недостаточно данных|не указан|не указано|нет данных|отсутствует",clean,re.I))
        # For abstentions, no fabricated nine-digit Russian BIK is acceptable.
        potential_bik=bool(re.search(r"(?<!\d)\d{9}(?!\d)",clean))
        result={
          "id":case["id"],"expected_abstained":case["expected_abstained"],
          "detected_abstention":abstain,"suspicious_bik":potential_bik if case["expected_abstained"] else False,
          "required_terms_present":present,"required_terms_total":len(required),
          "expected_citation_ids":expected_ids,"citation_ids_present":citations,
          "time_s":sec,"answer":clean[:1800],
          "terms_pass":len(present)==len(required),
          "citation_pass":len(citations)==len(expected_ids) if not case["expected_abstained"] else True,
          "abstention_pass":(abstain and not potential_bik) if case["expected_abstained"] else not abstain}
        results.append(result)
        print("CASE",result["id"],"terms",result["terms_pass"],"cite",result["citation_pass"],
              "abstain",result["abstention_pass"],"time",sec,flush=True)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps({"model":args.model,"results":results,"status":"in_progress"},ensure_ascii=False,indent=2)+"\n")
    result={"suite":"faithfulness_real_v1","suite_sha256":hashlib.sha256(frozen).hexdigest(),
            "model":"Qwen3.5-"+args.model+"-MLX-4bit","engine":"mlx-lm","load_s":loaded,
            "method":"Exploratory standalone prompt; not the same as official DP faithfulness scorer or Gemma 4 baseline",
            "results":results,
            "summary":{"cases":len(results),
                "required_terms_pass_rate":sum(x["terms_pass"] for x in results)/len(results),
                "citation_pass_rate":sum(x["citation_pass"] for x in results)/len(results),
                "abstention_pass_rate":sum(x["abstention_pass"] for x in results)/len(results),
                "combined_pass_rate":sum(x["terms_pass"] and x["citation_pass"] and x["abstention_pass"] for x in results)/len(results),
                "mean_time_s":round(sum(x["time_s"] for x in results)/len(results),3)}}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("SUMMARY",json.dumps(result["summary"]),flush=True)

if __name__=="__main__":main()
