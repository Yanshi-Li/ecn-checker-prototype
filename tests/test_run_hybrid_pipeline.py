import argparse
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RUN_HYBRID_PATH = ROOT / "scripts" / "run_hybrid.py"


spec = importlib.util.spec_from_file_location("run_hybrid", RUN_HYBRID_PATH)
run_hybrid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_hybrid)


def test_pipeline_runs_with_semantic_advisory_and_outputs(tmp_path, monkeypatch):
    ecn_path = tmp_path / "ecn.csv"
    bom_path = tmp_path / "bom.csv"
    out_dir = tmp_path / "out"

    ecn_path.write_text(
        "ecn_id,title,description,author,date,affected_parts,change_type\n"
        "ECN-SEM-001,Semantic test,Replace AB-1001 with AB-1002 for reliability,QA User,2026-08-14,RF600,add\n",
        encoding="utf-8",
    )
    bom_path.write_text(
        "line_number,part_number,description,quantity,unit,action,parent_part_no\n"
        "1,AB-1002,Replace bracket assembly,1,EA,ADD,DW900\n",
        encoding="utf-8",
    )

        
    monkeypatch.setattr(run_hybrid, "ROOT", tmp_path)
    monkeypatch.setattr(run_hybrid.dashboard_mod, "OUT_DIR", out_dir)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    args = argparse.Namespace(
        ecn=str(ecn_path),
        bom=str(bom_path),
        engineer_email="engineer@example.com",
        ce_email="ce@example.com",
    )

    packet = run_hybrid.run_pipeline(args)

    ai_flags = packet["validation"]["ai_flags"]
    assert ai_flags["ai_available"] is False
    assert any(flag.get("rule_id") == "A03" for flag in ai_flags["flags"])
    assert any(flag.get("rule_id") == "A04" for flag in ai_flags["flags"])
    assert any(flag.get("rule_id") == "A05" for flag in ai_flags["flags"])
    assert (out_dir / "dashboard.html").exists()
    assert (out_dir / "ai_summary.md").exists()
