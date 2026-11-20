"""Read-only structural review. Native roadmap stays the task source."""
import hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PIN="3900d42cfe76ba47c4d0b7ec98ce7620a0f31f11"
PRIOR="8b7d2cb0b98a463eb827b603101a83bd0bf0a192"
DIR="specs/001-consumer-roadmap-traceability"
SOURCES=json.loads("[{\"key\":\"DP\",\"path\":\"docs/ROADMAP.md\",\"sha256\":\"013c96b47041ddd70716cf340d9911b8af57d15c8163dca54d3ff6db986dcb9f\",\"expected_count\":27},{\"key\":\"CHECKPOINT\",\"path\":\".agent/current-task.yaml\",\"sha256\":\"e11a3ad95bcfd711166ca88d3fc9de372481b4b7e5bc91aee8a6fd9b56f01de9\",\"expected_count\":0}]")
def expected_rows(original):
    result={}
    for s in SOURCES:
        heading=0
        count=0
        for n,line in enumerate(original[s["path"]].decode("utf-8").splitlines(),1):
            if re.match(r"^#{1,6}\s",line):heading=n
            if not re.match(r"^\s*(?:[-*+]|\d+\.)\s+|^\s*\|",line) or not re.search(r"\[[ ~!]\]",line):continue
            k=f'{s["key"]}-{n:04d}'
            result[k]=(s["path"],n,heading,"".join(re.findall(r"\[([ ~!])\]",line)))
            count+=1
        if count!=s["expected_count"]:raise ValueError("baseline count: "+s["path"])
    return result
def validate(data,original,prior,current):
    errors=[]
    for s in SOURCES:
        p=s["path"];b=original[p]
        if hashlib.sha256(b).hexdigest()!=s["sha256"]:errors.append("source hash "+p)
        if not prior[p].startswith(b) or prior[p]!=current[p]:errors.append("unreviewed source change "+p)
    if data.get("schema")!="arvectum.native-roadmap-review/1" or data.get("source_commit")!=PIN or data.get("review_baseline")!=PRIOR or data.get("sources")!=SOURCES or data.get("execution_authorized") is not False or data.get("actual_acceptance_verified") is not False:errors.append("scope or authority")
    expected=expected_rows(original);rows=data.get("rows",[]);ids=[r["id"] for r in rows]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected):errors.append("remaining source coverage")
    for r in rows:
        k=r["id"]
        if k not in expected:continue
        if (r.get("source"),r.get("line"),r.get("heading_line"),r.get("markers"))!=expected[k]:errors.append("source/task linkage "+k)
        if k.startswith(("WHERE-","GROWTH-AGENT-")) and r.get("disposition")!="paused":errors.append("paused scope "+k)
        if r.get("disposition") not in {"paused","conditional_or_deferred","reconcile_required"}:errors.append("disposition "+k)
        if r.get("review_state") not in {"unverified","verified"}:errors.append("state "+k)
        if r.get("review_state")=="verified":
            ev=r.get("evidence",[])
            if not ev or any(e.get("criterion")!=k or e.get("outcome")!="pass" or not re.fullmatch(r"[0-9a-f]{64}",e.get("artifact_sha256","")) or not re.fullmatch(r"[0-9a-f]{40}",e.get("source_commit","")) or not e.get("receipt_ref") or not e.get("review_ref") for e in ev):errors.append("missing criterion-specific reviewed evidence "+k)
    return errors
def inputs():
    def read(ref,p):return subprocess.check_output(["git","-C",str(ROOT),"show",ref+":"+p])
    original={s["path"]:read(PIN,s["path"]) for s in SOURCES}
    prior={p:read(PRIOR,p) for p in original}
    current={p:(ROOT/p).read_bytes() for p in original}
    return json.loads((ROOT/DIR/"native-roadmap-review.json").read_text()),original,prior,current
if __name__=="__main__":
    errors=validate(*inputs())
    if errors:raise SystemExit("\n".join(errors))
    print("Structural source coverage PASS; actual acceptance and execution authorization remain separate.")
