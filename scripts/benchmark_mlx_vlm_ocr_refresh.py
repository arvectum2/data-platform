#!/usr/bin/env python3
"""MLX Qwen 2.5/3 vision on the existing two human-reviewed Russian scanned PDFs."""
from __future__ import annotations
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from benchmark_ocr_refresh import score

MODELS={"qwen2.5-vl-3b-mlx-4bit","qwen3-vl-4b-mlx-4bit","qwen3-vl-8b-mlx-4bit","paddleocr-vl-1.6-mlx-bf16","dots-ocr-mlx-bf16"}
PROMPT=("Перепиши весь видимый текст с изображения документа на русском языке максимально точно, "
"сохрани исходный порядок чтения, таблицы, числовые значения, даты, номера и поля форм. "
"Не добавляй объяснений, резюме или вымышленных данных. Выведи только распознанный текст.")
def main():
 a=argparse.ArgumentParser()
 a.add_argument("--model",choices=sorted(MODELS),required=True)
 a.add_argument("--output",type=Path,required=True)
 a.add_argument("--max-tokens",type=int,default=3000)
 args=a.parse_args()
 if args.model.startswith("dots-"):
  raise SystemExit("dots.ocr BF16 exceeded shared Mac mini 24GiB safety budget; do not rerun while production services are resident. Test a quantized adapter or GPU VPS instead.")
 root=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks")
 modelpath=(root/'quality-results'/args.model) if args.model.endswith('-mlx-bf16') else root/args.model
 suite=Path(__file__).resolve().parents[1]/"benchmarks/corpora/public_v2/manifest.json"
 raw=suite.read_bytes();cases=[x for x in json.loads(raw)["artifacts"] if x.get("ocr_required") and x.get("gold_text_file")]
 assert len(cases)==2
 from mlx_vlm import load,generate
 from mlx_vlm.prompt_utils import apply_chat_template
 from mlx_vlm.utils import load_config
 print("LOADING",modelpath,flush=True)
 start=time.perf_counter()
 model,processor=load(str(modelpath),lazy=False)
 config=load_config(str(modelpath))
 load_s=round(time.perf_counter()-start,3)
 print("LOADED",load_s,flush=True)
 runs=[]
 for c in cases:
  page=suite.parent/c["file"];gold=suite.parent/c["gold_text_file"]
  assert hashlib.sha256(page.read_bytes()).hexdigest()==c["sha256"]
  assert hashlib.sha256(gold.read_bytes()).hexdigest()==c["gold_sha256"]
  tmp=root/"quality-results"/"vision-input"/c["id"]
  tmp.parent.mkdir(parents=True,exist_ok=True)
  subprocess.run(["pdfimages","-png",str(page),str(tmp)],check=True,stdout=subprocess.DEVNULL)
  files=sorted(tmp.parent.glob(c["id"]+"-*.png"))
  assert files, "Failed to extract raster PDF image"
  dots_prompt=("Please output the layout information from the PDF image, including each layout element's bbox, "
               "category, and the corresponding original text, reading order. Return a JSON array "
               "of {category,bbox,text} objects, and do not translate text.")
  task_prompt=("Transcribe this document to markdown." if args.model.startswith("paddleocr-") else
               dots_prompt if args.model.startswith("dots-") else PROMPT)
  prompt=apply_chat_template(processor,config,task_prompt,num_images=1)
  start=time.perf_counter()
  answer=generate(model,processor,prompt,image=[str(files[0])],max_tokens=args.max_tokens,temperature=0.0,verbose=False)
  elapsed=round(time.perf_counter()-start,3)
  text=answer.text if hasattr(answer,"text") else str(answer)
  if args.model.startswith("dots-"):
   try:
    obj=json.loads(text)
    elements=obj.get("layout_elements",obj.get("elements",obj)) if isinstance(obj,dict) else obj
    if isinstance(elements,list):
     flat=" ".join(str(v.get("text","")) for v in elements if isinstance(v,dict))
     if flat.strip():text_for_score=flat
     else:text_for_score=text
    else:text_for_score=text
   except (json.JSONDecodeError,AttributeError):text_for_score=text
  else:text_for_score=text
  result={"id":c["id"],"latency_s":elapsed,
          **score(gold.read_text(),text_for_score,c["required_text"]),
          "output":text[:12000]}
  runs.append(result)
  print("CASE",c["id"],{k:result[k] for k in ["cer","wer","latency_s","required_text_passed"]},flush=True)
  args.output.parent.mkdir(parents=True,exist_ok=True)
  args.output.write_text(json.dumps({"model":args.model,"backend":"mlx-vlm","suite_sha256":hashlib.sha256(raw).hexdigest(),
                                    "load_s":load_s,"cases":runs},ensure_ascii=False,indent=2)+"\n")
 print("DONE",args.model,flush=True)
if __name__=="__main__":main()
