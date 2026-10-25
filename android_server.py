"""Embedded local Flask server for the Android app."""
import os
import threading
from werkzeug.serving import make_server

_server = None
_thread = None
_lock = threading.Lock()

def start_server(files_dir):
    global _server, _thread
    with _lock:
        if _server is not None:
            return "already-running"
        # Persist database inside Android's private app storage, not the APK bundle.
        os.environ["GATE_DB"] = os.path.join(files_dir, "gate.db")
        # Several legacy routes use relative static/ paths, so set a stable working directory.
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        os.environ["GATE_AI_API_KEY"] = os.environ.get("GATE_AI_API_KEY", "")
        import app as gate_app
        _server = make_server("127.0.0.1", 5000, gate_app.app, threaded=True)
        _thread = threading.Thread(target=_server.serve_forever, name="gate-flask", daemon=True)
        _thread.start()
        return "started"
