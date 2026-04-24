import os
import tempfile
import threading
import uuid
from pathlib import Path

from botocore.exceptions import ClientError
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from rag_engine import (
    fetch_all_cis_points,
    generate_master_script_from_cis_points,
    ingest_document,
    run_rag_query,
)


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"

app = Flask(__name__, static_folder=str(FRONTEND_DIST_DIR), static_url_path="")
CORS(app)
MASTER_SCRIPT_JOBS = {}
MASTER_SCRIPT_JOBS_LOCK = threading.Lock()


def normalize_os_type(raw_value):
    os_type = (raw_value or "linux").strip().lower()
    return os_type if os_type in {"linux", "windows"} else "linux"


def format_bedrock_error(exc):
    message = str(exc)

    if "on-demand throughput isn" in message or "on-demand throughput isn't supported" in message:
        return (
            "Bedrock requires an inference profile for this model. "
            "Set BEDROCK_INFERENCE_PROFILE_ID in your environment or .env, "
            "for example apac.amazon.nova-lite-v1:0, and ensure your IAM user "
            "has bedrock:InvokeModel permission on that inference-profile ARN."
        )

    if "AccessDeniedException" in message:
        return (
            "Bedrock access was denied. Check that your IAM policy allows "
            "bedrock:InvokeModel for the configured model or inference profile."
        )

    return f"Bedrock request failed: {message}"


def update_master_script_job(job_id, **updates):
    with MASTER_SCRIPT_JOBS_LOCK:
        if job_id in MASTER_SCRIPT_JOBS:
            MASTER_SCRIPT_JOBS[job_id].update(updates)


def build_master_script_job(job_id, os_type):
    def progress_callback(batch_number, total_batches, total_controls, processed_controls, batch):
        update_master_script_job(
            job_id,
            status="running",
            batch_number=batch_number,
            total_batches=total_batches,
            processed_controls=processed_controls,
            total_controls=total_controls,
            current_control_start=batch[0]["id"],
            current_control_end=batch[-1]["id"],
            progress_message=(
                f"Processed {processed_controls} of {total_controls} control IDs "
                f"(batch {batch_number}/{total_batches})."
            ),
        )

    try:
        update_master_script_job(job_id, status="running", progress_message="Collecting control IDs...")
        script = generate_master_script_from_cis_points(os_type, progress_callback=progress_callback)
        extension = "ps1" if os_type == "windows" else "sh"
        language = "powershell" if os_type == "windows" else "bash"
        update_master_script_job(
            job_id,
            status="completed",
            script=script,
            filename=f"cis_hardening_{os_type}.{extension}",
            language=language,
            os_type=os_type,
            progress_message="Master script completed."
        )
    except ClientError as exc:
        update_master_script_job(job_id, status="failed", error=format_bedrock_error(exc))
    except Exception as exc:
        update_master_script_job(job_id, status="failed", error=str(exc))


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/controls")
def get_controls():
    os_type = normalize_os_type(request.args.get("os_type"))
    print("os_type:", os_type)
    controls = fetch_all_cis_points(os_type)
    return jsonify(
        {
            "os_type": os_type,
            "count": len(controls),
            "controls": controls,
        }
    )


@app.post("/api/ingest")
def ingest():
    os_type = normalize_os_type(request.form.get("os_type"))
    print("os_type:", os_type)
    uploaded_file = request.files.get("file")
    print("uploaded_file",uploaded_file)

    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({"error": "Please upload a PDF file."}), 400

    if not uploaded_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF uploads are supported."}), 400

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            uploaded_file.save(tmp_file)
            temp_path = tmp_file.name

        ingest_document(temp_path, os_type)
        return jsonify(
            {
                "message": f"Ingested {os_type} document successfully.",
                "filename": uploaded_file.filename,
                "os_type": os_type,
            }
        )
    except ClientError as exc:
        return jsonify({"error": format_bedrock_error(exc)}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@app.post("/api/query")
def query():
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("query") or "").strip()
    os_type = normalize_os_type(payload.get("os_type"))

    if not prompt:
        return jsonify({"error": "Please provide a query."}), 400

    try:
        result = run_rag_query(
            prompt,
            os_type,
            k=5,
            score_threshold=1.0,
            include_validation=True,
        )
        return jsonify({"result": result, "os_type": os_type})
    except ClientError as exc:
        return jsonify({"error": format_bedrock_error(exc)}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/master-script")
def master_script():
    payload = request.get_json(silent=True) or {}
    os_type = normalize_os_type(payload.get("os_type"))
    job_id = uuid.uuid4().hex

    with MASTER_SCRIPT_JOBS_LOCK:
        MASTER_SCRIPT_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "os_type": os_type,
            "processed_controls": 0,
            "total_controls": 0,
            "batch_number": 0,
            "total_batches": 0,
            "progress_message": "Queued master script build...",
            "script": "",
            "filename": "",
            "language": "",
            "error": "",
        }

    thread = threading.Thread(target=build_master_script_job, args=(job_id, os_type), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued", "os_type": os_type}), 202


@app.get("/api/master-script/<job_id>")
def master_script_status(job_id):
    with MASTER_SCRIPT_JOBS_LOCK:
        job = MASTER_SCRIPT_JOBS.get(job_id)

    if job is None:
        return jsonify({"error": "Master script job not found."}), 404

    return jsonify(job)


@app.get("/")
def serve_index():
    if FRONTEND_DIST_DIR.exists():
        return send_from_directory(FRONTEND_DIST_DIR, "index.html")
    return jsonify(
        {
            "message": "React frontend not built yet.",
            "next_steps": [
                "cd frontend",
                "npm install",
                "npm run build",
                "python app.py",
            ],
        }
    )


@app.get("/<path:path>")
def serve_static(path):
    if FRONTEND_DIST_DIR.exists():
        target = FRONTEND_DIST_DIR / path
        if target.exists():
            return send_from_directory(FRONTEND_DIST_DIR, path)
        return send_from_directory(FRONTEND_DIST_DIR, "index.html")
    return jsonify({"error": "Frontend asset not found."}), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes"}
    app.run(debug=debug, host="0.0.0.0", port=port)
