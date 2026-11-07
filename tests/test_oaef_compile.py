"""Spec compiler (C1): generated contract up to date, traceability, and spec errors rejected."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAS_YAML = importlib.util.find_spec('yaml') is not None


@unittest.skipUnless(HAS_YAML, 'PyYAML not installed (pip install --require-hashes -r requirements-compiler.txt)')
class CompilerTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import oaef_compile
        self.c = oaef_compile

    def test_generated_contract_is_up_to_date(self):
        p = subprocess.run([sys.executable, str(ROOT / 'tools/oaef_compile.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_traceability_to_requirements_and_model(self):
        contract = json.loads((ROOT / 'generated/contracts/NIN-001.contract.json').read_text(encoding='utf-8'))
        ob = {o['obligation_id']: o for o in contract['obligations']}
        uin = ob['OBL-EVENTS-EV_UIN_ASSIGNED']
        self.assertEqual(uin['requirement_refs'], ['F-07'])
        self.assertTrue(any('Assign exactly one NIN' in m['activity'] for m in uin['model_element_refs']))
        self.assertIn('NF-08', ob['OBL-TRACES-PKR_SERVER']['requirement_refs'])    # cross-cutting signal contract
        self.assertEqual(ob['OBL-EVENTS-NF-04']['requirement_refs'], ['NF-04'])
        self.assertTrue(all(o['requirement_refs'] for o in contract['obligations'] if o['section'] in ('traces', 'events')))

    def test_broken_reference_in_spec_is_rejected(self):
        import yaml
        spec = yaml.safe_load((ROOT / 'oracles/NIN-001.oracle.yaml').read_text(encoding='utf-8'))
        spec['traces']['spans'][3]['parent'] = 'NO_SUCH_ALIAS'
        bad = ROOT / 'generated' / '_tmp_bad.oracle.yaml'
        bad.write_text(yaml.safe_dump(spec), encoding='utf-8')
        try:
            with self.assertRaises(self.c.SpecError):
                self.c.compile_spec('NIN-001', 'generated/_tmp_bad.oracle.yaml',
                                    self.c.read_requirements(), self.c.read_activities())
        finally:
            bad.unlink()


if __name__ == '__main__':
    unittest.main()
