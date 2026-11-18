import json
import subprocess
import sys
from pathlib import Path

from check_template import first_difference, normalise

ROOT = Path(__file__).resolve().parents[2]


def test_ignores_compiler_metadata_and_line_endings():
    a = {"metadata": {"_generator": {"version": "0.49"}}, "variables": {"s": "a\r\nb"}, "resources": [{"properties": {"templateHash": "1", "x": 1}}]}
    b = {"metadata": {"_generator": {"version": "0.43"}}, "variables": {"s": "a\nb"}, "resources": [{"properties": {"templateHash": "2", "x": 1}}]}
    assert first_difference(normalise(a), normalise(b)) is None


def test_detects_real_differences():
    a = {"resources": [{"properties": {"image": "python:3.12"}}]}
    b = {"resources": [{"properties": {"image": "python:3.13"}}]}
    assert first_difference(normalise(a), normalise(b)) == "$.resources[0].properties.image: values differ"
    assert first_difference({"a": 1}, {"b": 1}) is not None


def test_committed_template_is_valid_json_and_has_no_function_app():
    t = json.loads((ROOT / "infra" / "azuredeploy.json").read_text(encoding="utf-8"))
    assert "packageUri" in t["parameters"] and "codePackageUri" not in t["parameters"]
    text = json.dumps(t)
    assert "Microsoft.Web/sites" not in text and "Microsoft.Storage/storageAccounts" not in text
    assert "Microsoft.App/jobs" in text


def test_cli_exit_codes(tmp_path):
    f = tmp_path / "a.json"
    f.write_text("{}", encoding="utf-8")
    ok = subprocess.run([sys.executable, str(ROOT / "tools" / "check_template.py"), str(f), str(f)], capture_output=True, text=True)
    assert ok.returncode == 0
