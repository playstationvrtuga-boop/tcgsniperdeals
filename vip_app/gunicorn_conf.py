import os


bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "sync")
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
preload_app = False
_accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-").strip().lower()
accesslog = None if _accesslog in {"", "0", "false", "off", "none"} else os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
