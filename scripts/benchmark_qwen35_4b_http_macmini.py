#!/usr/bin/env python3
"""Read-only Qwen3.5-4B MLX OpenAI-HTTP comparison using frozen Russian public evidence."""
from __future__ import annotations
import hashlib,json,re,statistics,time,urllib.request,zipfile,subprocess,os
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"benchmarks/faithfulness_real_v1.json"
SIZE=os.getenv('ARVECTUM_BENCH_MLX_SIZE','4b')
assert SIZE in {'4b','9b'}
M=Path('/Volumes/ArvectumSSD/Models/data-platform-benchmarks')/f'qwen3.5-{SIZE}-mlx-4bit'
OUT=Path('/Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results')/f'qwen35-{SIZE}-http-real-context.json'
SYS=("Ты анализируешь только предоставленные фрагменты документов. "
"Нельзя добавлять факты вне этих фрагментов. Если данных недостаточно, "
"напиши строго: 'Недостаточно данных в источниках.' "
"В остальных случаях дай краткий ответ на русском, затем отдельной строкой "
"'Источники: [ID]' для каждого использованного фрагмента. "
"Ответ должен содержать точные номера, суммы и названия без изменения.")
def request(user,max_tokens=360):
 data={"model":str(M),"messages":[{"role":"system","content":SYS},
        {"role":"user","content":user}],"temperature":0,"max_tokens":max_tokens}
 req=urllib.request.Request("http://127.0.0.1:18081/v1/chat/completions",
 data=json.dumps(data,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json"})
 t=time.monotonic()
 with urllib.request.urlopen(req,timeout=150) as r:
  payload=json.load(r)
 return payload["choices"][0]["message"]["content"],round(time.monotonic()-t,3),payload.get("usage",{})
def docx_text(path):
 with zipfile.ZipFile(path) as z:
  t=ET.fromstring(z.read("word/document.xml"))
 key="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
 paragraph="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
 return "\n".join("".join(n.text or "" for n in p.iter(key)) for p in t.iter(paragraph))
def main():
 raw=FILE.read_bytes()
 cases=json.loads(raw)["cases"]
 results=[]
 for c in cases:
  evidence="\n".join("[{}] {}".format(e["chunk_id"],e["text"]) for e in c["evidence"])
  a,sec,usage=request(f"Вопрос: {c['query']}\nИсточники:\n{evidence}\nОтветь без рассуждений.")
  clean=re.sub(r"<think>.*?</think>","",a,flags=re.DOTALL).strip()
  terms=all(x.casefold() in clean.casefold() for x in c.get("required_answer_terms",[]))
  ids={x for claim in c.get("required_claims",[]) for x in claim.get("expected_chunk_ids",[])}
  refs={k.strip() for grp in re.findall(r"\[([^\]]+)\]",clean) for k in grp.split(",")}
  citations=ids.issubset(refs) if not c["expected_abstained"] else True
  abstain=bool(re.search(r"недостаточно данных|не указан|не указано|нет данных|отсутствует",clean,re.I))
  fake=bool(re.search(r"(?<!\d)\d{9}(?!\d)",clean)) if c["expected_abstained"] else False
  abst_pass=abstain and not fake if c["expected_abstained"] else not abstain
  results.append({"case":c["id"],"terms_pass":terms,"citations_pass":citations,"abstention_pass":abst_pass,
                  "seconds":sec,"text":clean[:1300],"usage":usage})
  print("CASE",c["id"],"pass",terms and citations and abst_pass,"latency",sec,flush=True)
 pub=ROOT/"benchmarks/corpora/public_v2/fixtures"
 control=subprocess.check_output(["pdftotext","-layout",str(pub/"procurement_control_notice.pdf"),"-"]).decode()
 nmck=docx_text(pub/"procurement_nmck.docx")
 # All chunks are drawn from frozen PUBLIC files and presented as model evidence.
 additional=[
  {"id":"long-cross-source","q":"Назови орган контроля и код ОКУД из первого документа, а НМЦК книгоиздательской продукции из второго. Сохрани точное название, номер и сумму. Укажи оба источника.","needed":["Комитет финансов Санкт-Петербурга","0506135","299 967,00"],"sources":["control","nmck"],"docs":[control[:7000],nmck[:9500]]},
  {"id":"long-missing-bank-bik","q":"Каков банковский БИК заказчика? Если нет подтверждения во фрагментах, прямо скажи об этом.","needed":[],"sources":["control","nmck"],"docs":[control[:7000],nmck[:9500]],"abstain":True}]
 for c in additional:
  prompt="Вопрос: "+c["q"]+"\nИсточники:\n"+"\n".join(f'[{i}] {d}' for i,d in zip(c["sources"],c["docs"]))+"\nОтветь без рассуждений."
  answer,sec,usage=request(prompt,max_tokens=370)
  clean=answer.strip()
  term=all(x.casefold() in clean.casefold() for x in c["needed"])
  ids={k.strip() for grp in re.findall(r"\[([^\]]+)\]",clean) for k in grp.split(",")}
  cited=all(x in ids for x in c["sources"]) if not c.get("abstain") else True
  abst=bool(re.search(r"недостаточно данных|не указан|не указано|нет данных|отсутствует|не содержится",clean,re.I))
  nofake=not bool(re.search(r"(?<!\d)\d{9}(?!\d)",clean))
  abst_pass=(abst and nofake) if c.get("abstain") else not abst
  results.append({"case":c["id"],"terms_pass":term,"citations_pass":cited,"abstention_pass":abst_pass,
                  "seconds":sec,"text":clean[:1300],"usage":usage})
  print("CASE",c["id"],"pass",term and cited and abst_pass,"latency",sec,flush=True)
 result={"model":f"Qwen3.5-{SIZE}-MLX-4bit","endpoint":"isolated localhost:18081",
   "method":"7 lightweight lexical/source-ID/abstention checks on 5 frozen caselets + 2 full-document contexts; not full hallucination adjudication",
   "baseline_sha256":hashlib.sha256(raw).hexdigest(),"cases":results,
   "mean_latency_s":round(statistics.mean(r["seconds"] for r in results),3),
   "passed_cases":sum(r["terms_pass"] and r["citations_pass"] and r["abstention_pass"] for r in results),
   "total_cases":len(results),"production_changed":False}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
 print("SUMMARY",result["passed_cases"],"/",result["total_cases"],"mean_s",result["mean_latency_s"],flush=True)
if __name__=="__main__":main()
