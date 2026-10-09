#!/usr/bin/env python3
"""Download official Russian model candidates to an isolated ArvectumSSD batch.

No production model/service mutations. Python requirements:
  pip install "huggingface_hub>=1.0"
Run after Mac mini regains macOS access to external ArvectumSSD:
  python3 scripts/download_russian_model_candidates.py
  python3 scripts/download_russian_model_candidates.py --all
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

ROOT=Path("/Volumes/ArvectumSSD/Models/data-platform-benchmarks")
CACHE=Path("/Volumes/ArvectumSSD/Models/huggingface-cache/hub")
OUT=ROOT/"russian-models"
PATTERNS=["*.safetensors","*.json","*.py","*.model","*.txt","*.jinja","README.md","LICENSE","*.tiktoken","*.yaml"]
MODELS=[
 {"name":"giga-embeddings-0826-480m","repo":"ai-sage/Giga-Embeddings-instruct-480M-0826","revision":"1763d603adac","role":"embedding","files":PATTERNS,"optional":False},
 {"name":"giga-embeddings-0826-3b","repo":"ai-sage/Giga-Embeddings-instruct-3B-0826","revision":"b71168088212","role":"embedding","files":PATTERNS,"optional":False},
 {"name":"gigachat-3.1-lightning-q4","repo":"ai-sage/GigaChat3.1-10B-A1.8B-GGUF","revision":"97045b260251","role":"generation","files":["*q4_K_M.gguf","README.md","LICENSE"],"optional":False},
 {"name":"giga-embeddings-2025-3b","repo":"ai-sage/Giga-Embeddings-instruct","revision":"2cf0fdc97194","role":"embedding","files":PATTERNS,"optional":True},
 {"name":"giga-embeddings-0826-10b","repo":"ai-sage/Giga-Embeddings-instruct-10B-A1.8B-0826","revision":"3bca8f1e0147","role":"embedding","files":PATTERNS,"optional":True},
]
EXT={".gguf",".safetensors"}
def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open("rb") as fp:
  while True:
   chunk=fp.read(8*1024*1024)
   if not chunk:break
   h.update(chunk)
 return h.hexdigest()

def main()->None:
 parser=argparse.ArgumentParser()
 parser.add_argument("--all",action="store_true",help="Also archive legacy 2025 3B and heavy 0826 10B BF16 weights")
 args=parser.parse_args()
 # macOS TCC denial is a hard stop: do not silently redirect storage to internal disk.
 try:
  if not ROOT.is_dir():raise RuntimeError("Missing SSD model directory")
  list(ROOT.iterdir())
  OUT.mkdir(parents=True,exist_ok=True)
  CACHE.mkdir(parents=True,exist_ok=True)
 except OSError as exc:
  raise SystemExit(f"Cannot access ArvectumSSD: {exc}. Restore macOS access; no fallback to internal disk.")
 except RuntimeError as exc:raise SystemExit(str(exc))
 api=HfApi()
 existing=OUT/"manifest.json"
 entries=json.loads(existing.read_text()) if existing.exists() else {"models":{}}
 for cfg in MODELS:
  name=cfg["name"]
  if cfg["optional"] and not args.all:
   print("SKIP optional",name,flush=True)
   continue
  item={"repo":cfg["repo"],"role":cfg["role"],"status":"started","checked_at":datetime.now(timezone.utc).isoformat()}
  try:
   info=api.model_info(cfg["repo"],revision=cfg["revision"],files_metadata=True)
   files={x.rfilename:int(x.size or 0) for x in info.siblings if x.rfilename.endswith(tuple(EXT))}
   snap=Path(snapshot_download(repo_id=cfg["repo"],revision=info.sha,cache_dir=str(CACHE),
            allow_patterns=cfg["files"],max_workers=3))
   local={}
   for filename,size in files.items():
    f=snap/filename
    if not f.exists():continue
    actual=f.stat().st_size
    if actual!=size:raise RuntimeError(f"{name}: size mismatch {filename}: {actual}!={size}")
    local[filename]={"bytes":actual,"sha256":sha256(f)}
   if not local:raise RuntimeError(f"{name}: no complete weight files")
   link=OUT/name
   if link.is_symlink():
    if link.resolve()!=snap.resolve():raise RuntimeError(f"{name}: different existing snapshot link, refusing overwrite")
   elif link.exists():raise RuntimeError(f"{name}: path already exists, refusing overwrite")
   else:link.symlink_to(snap,target_is_directory=True)
   item.update(status="ready",revision=info.sha,path=str(link),weights=local,total_weight_bytes=sum(z["bytes"] for z in local.values()))
  except Exception as exc:
   item.update(status="error",detail=str(exc))
  entries["models"][name]=item
  entries["updated_at"]=datetime.now(timezone.utc).isoformat()
  tmp=OUT/"manifest.json.tmp"
  tmp.write_text(json.dumps(entries,ensure_ascii=False,indent=2)+"\n")
  tmp.replace(existing)
  print(name,item["status"],item.get("total_weight_bytes",0),flush=True)
 print("DONE",sum(x["status"]=="ready" for x in entries["models"].values()),"ready",flush=True)
 if any(x["status"]=="error" for x in entries["models"].values()):raise SystemExit(1)

if __name__=="__main__":main()
