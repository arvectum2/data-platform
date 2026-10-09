#!/usr/bin/env python3
"""Evaluate current production Gemma read-only on same frozen 5 Russian cases."""
from __future__ import annotations
import hashlib,json,re,statistics,time,urllib.request
from pathlib import Path
from benchmark_gigachat_reasoning_refresh import chat
def main():
 repo=Path(__file__).resolve().parents[1]
 suite=repo/"benchmarks/faithfulness_real_v1.json"
 raw=suite.read_bytes();cases=json.loads(raw)["cases"]
 with urllib.request.urlopen("http://127.0.0.1:8081/v1/models",timeout=10) as resp:
  meta=json.load(resp)
 alias=meta["data"][0]["id"]
 print("PRODUCTION_READ_ONLY",alias,flush=True)
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
  start=time.perf_counter()
  answer,usage=chat(8081,alias,system,user)
  sec=round(time.perf_counter()-start,3)
  clean=re.sub(r"<think>.*?</think>","",answer,flags=re.DOTALL).strip()
  required=c.get("required_answer_terms") or []
  ids=sorted(set(x for claim in c.get("required_claims",[]) for x in claim["expected_chunk_ids"]))
  if not ids:ids=[x["chunk_id"] for x in c["evidence"]]
  abstain=bool(re.search(r"недостаточно данных|не указан|не указано|нет данных|отсутствует",clean,re.I))
  bik=bool(re.search(r"(?<!\d)\d{9}(?!\d)",clean)) if c["expected_abstained"] else False
  r={"id":c["id"],"terms_pass":all(t.casefold() in clean.casefold() for t in required),
   "citation_pass":True if c["expected_abstained"] else all("["+s+"]" in clean for s in ids),
   "abstention_pass":(abstain and not bik) if c["expected_abstained"] else not abstain,
   "seconds":sec,"answer":clean[:1800],"usage":usage}
  results.append(r)
  print("CASE",r["id"],r["terms_pass"],r["citation_pass"],r["abstention_pass"],sec,flush=True)
 summary={"cases":len(results),"terms_pass":sum(r["terms_pass"] for r in results)/len(results),
  "citations_pass":sum(r["citation_pass"] for r in results)/len(results),
  "abstention_pass":sum(r["abstention_pass"] for r in results)/len(results),
  "combined_pass":sum(r["terms_pass"] and r["citation_pass"] and r["abstention_pass"] for r in results)/len(results),
  "mean_time_s":round(statistics.mean(r["seconds"] for r in results),3)}
 result={"model":alias,"engine":"llama.cpp","endpoint":"existing live production :8081 read-only",
 "suite":"faithfulness_real_v1","suite_sha256":hashlib.sha256(raw).hexdigest(),
 "method":"same prompt/content as GigaChat and Qwen3.5; heuristic not official acceptance","cases":results,"summary":summary}
 out=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results/gemma-live-5case.json")
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
 print("SUMMARY",json.dumps(summary),flush=True)
if __name__=="__main__":main()
