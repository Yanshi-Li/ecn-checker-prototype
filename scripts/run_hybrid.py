import json
import sys
from pathlib import Path

from ai_assistant import generate_assistant_output
from ecn_checker import run_checker
from plugin_workflow import build_plugin_payload, write_plugin_dashboard
from single_ecn_workflow import build_single_ecn_view, write_single_ecn_dashboard


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
DASHBOARD_JSON = OUT_DIR / "ecn-dashboard.json"
AI_OUTPUT = OUT_DIR / "ai-summary.json"
HYBRID_HTML = OUT_DIR / "hybrid-dashboard.html"
PLUGIN_HTML = OUT_DIR / "plugin-workflow.html"
SINGLE_ECN_HTML = OUT_DIR / "single-ecn-workflow.html"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    dashboard = run_checker(ROOT / "data", OUT_DIR)

    if not DASHBOARD_JSON.exists():
        raise FileNotFoundError(f"Expected dashboard JSON at {DASHBOARD_JSON}")
    generate_assistant_output(dashboard, AI_OUTPUT, HYBRID_HTML)

    plugin_payload = build_plugin_payload(dashboard)
    write_plugin_dashboard(plugin_payload, PLUGIN_HTML)

    single_ecn_payload = build_single_ecn_view(dashboard)
    write_single_ecn_dashboard(single_ecn_payload, SINGLE_ECN_HTML)
    return 0


if __name__ == "__main__":
    sys.exit(main())