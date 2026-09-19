import os
import threading
import uuid

from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS

from jobs import JOBS, JOBS_LOCK, make_job
from pipeline import background_process

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    body    = request.json or {}
    url     = body.get("url", "").strip()
    context = body.get("context", "").strip()

    if not url:
        return jsonify({"error": "Please provide a video URL"}), 400

    task_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[task_id] = make_job()

    threading.Thread(
        target=background_process,
        args=(task_id, url, context),
        daemon=True
    ).start()

    return jsonify({"task_id": task_id})


@app.route("/status/<task_id>")
def status(task_id):
    with JOBS_LOCK:
        job = JOBS.get(task_id)
        if not job:
            return jsonify({"error": "Unknown task_id"}), 404
        return jsonify(job)


@app.route("/sw.js")
def service_worker():
    return Response("""
const CACHE='deepcheck-v12';
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/']))));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
""", mimetype="application/javascript")


if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("RENDER") is None
    app.run(host="0.0.0.0", port=port, debug=debug)