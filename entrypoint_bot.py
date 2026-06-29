"""
Kuberns entrypoint for the Telegram BM bot.

1. Starts a tiny health-check HTTP server on port 8000 (daemon thread).
2. Imports main.py which initialises the telebot.TeleBot instance and registers handlers.
3. Calls bot.infinity_polling() to process Telegram updates forever.
"""
import threading
import http.server
import socketserver
import time
import sys


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass  # suppress request logs


def run_health_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", 8000), HealthHandler) as httpd:
        httpd.serve_forever()


# ── Start health server before anything else ─────────────────────────────────
health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()
time.sleep(0.3)  # let the socket bind

# ── Import bot module (registers all handlers, validates tokens) ──────────────
try:
    import main as bot_module
except Exception as exc:
    print(f"FATAL: failed to initialise bot — {exc}", file=sys.stderr)
    sys.exit(1)

# ── Start polling ─────────────────────────────────────────────────────────────
print("Бот запущен и полностью готов к работе!")
bot_module.bot.infinity_polling()
