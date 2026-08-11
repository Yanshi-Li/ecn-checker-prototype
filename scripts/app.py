from __future__ import annotations
import os
import sys
import csv
import io

print("=== app.py starting ===", flush=True)

# Must come before importing ecn_checker
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, render_template, jsonify
from ecn_checker import run_checks

# Resolve paths relative to repo root, not scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(ROOT, "templates"),
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB limit


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() == "csv"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    role = request.form.get("role", "ecn_creator")
    uploaded = request.files.getlist("files")

    if not uploaded or all(f.filename == "" for f in uploaded):
        return jsonify({"error": "No files selected."}), 400

    results = []
    file_data = {}

    for f in uploaded:
        if not allowed_file(f.filename):
            results.append({
                "file": f.filename,
                "issues": [{"rule": "UPLOAD", "severity": "error",
                             "message": "Only CSV files are accepted."}]
            })
            continue
        content = f.read().decode("utf-8-sig")
        file_data[f.filename] = content

    check_results = run_checks(file_data, role=role)
    results.extend(check_results)

    summary = {
        "total_files": len(uploaded),
        "total_issues": sum(len(r.get("issues", [])) for r in results),
        "errors":   sum(1 for r in results for i in r.get("issues", []) if i["severity"] == "error"),
        "warnings": sum(1 for r in results for i in r.get("issues", []) if i["severity"] == "warning"),
    }

    return jsonify({"summary": summary, "results": results})


if __name__ == "__main__":
    print(f"Templates folder: {os.path.join(ROOT, 'templates')}", flush=True)
    print(f"templates/index.html exists: {os.path.exists(os.path.join(ROOT, 'templates', 'index.html'))}", flush=True)
    app.run(debug=True, port=5000)