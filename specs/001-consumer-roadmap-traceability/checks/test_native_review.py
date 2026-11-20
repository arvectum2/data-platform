import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("gate",Path(__file__).with_name("check_native_review.py"))
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class Cases(unittest.TestCase):
    def setUp(self):self.d,self.o,self.p,self.c=gate.inputs()
    def run_gate(self):return gate.validate(self.d,self.o,self.p,self.c)
    def test_valid(self):self.assertEqual(self.run_gate(),[])
    def test_lost(self):self.d["rows"].pop();self.assertIn("remaining source coverage",self.run_gate())
    def test_duplicate(self):self.d["rows"].append(self.d["rows"][0]);self.assertTrue(self.run_gate())
    def test_hierarchy(self):self.d["rows"][0]["heading_line"]=-1;self.assertTrue(self.run_gate())
    def test_source_drift(self):self.c[next(iter(self.c))]+=b"\n";self.assertTrue(self.run_gate())
    def test_fake_completion(self):self.d["rows"][0]["review_state"]="verified";self.assertTrue(self.run_gate())
    def test_authority(self):self.d["execution_authorized"]=True;self.assertTrue(self.run_gate())
    def test_wrong_evidence(self):
        r=self.d["rows"][0];r["review_state"]="verified";r["evidence"]=[{"criterion":"wrong","outcome":"pass","artifact_sha256":"a"*64,"source_commit":"b"*40,"receipt_ref":"r","review_ref":"r"}];self.assertTrue(self.run_gate())
