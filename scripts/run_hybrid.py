import json
import subprocess
import sys
from pathlib import Path

from ai_assistant import generate_assistant_output
from plugin_workflow import build_plugin_payload, write_plugin_dashboard


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
DASHBOARD_JSON = OUT_DIR / "ecn-dashboard.json"
AI_OUTPUT = OUT_DIR / "ai-summary.json"
HYBRID_HTML = OUT_DIR / "hybrid-dashboard.html"
PLUGIN_HTML = OUT_DIR / "plugin-workflow.html"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    subprocess.run(["javac", "-d", str(OUT_DIR), "src/EcnCheckerSimulation.java"], cwd=ROOT, check=True)
    subprocess.run(["java", "-cp", str(OUT_DIR), "EcnCheckerSimulation"], cwd=ROOT, check=True)

    if not DASHBOARD_JSON.exists():
        raise FileNotFoundError(f"Expected dashboard JSON at {DASHBOARD_JSON}")

    dashboard = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
    generate_assistant_output(dashboard, AI_OUTPUT, HYBRID_HTML)

    plugin_payload = build_plugin_payload(dashboard)
    write_plugin_dashboard(plugin_payload, PLUGIN_HTML)

    print(f"AI assistant output written to {AI_OUTPUT}")
    print(f"Hybrid dashboard written to {HYBRID_HTML}")
    print(f"Plugin workflow view written to {PLUGIN_HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
