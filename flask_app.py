from flask import Flask, request, jsonify
import os
import logging
import asyncio
import ui_bot_handler

logger = logging.getLogger(__name__)
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True)
    msg = data.get("message") or data.get("edited_message")
    if not msg:
        return jsonify({"ok": True})

    chat_id = str(msg.get("chat", {}).get("id"))
    text = msg.get("text", "")
    if chat_id == os.getenv("CHAT_ID"):
        # Set the global response and notify via ui_bot_handler
        ui_bot_handler.user_response = text
        ui_bot_handler.response_event.set()
        logger.info(f"UI bot received response: {text}")
    else:
        logger.warning(f"Unauthorized chat ID: {chat_id}")
    return jsonify({"ok": True})


def run_flask_app(host: str, port: int):
    """Blocking call to start Flask (used in executor)"""
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port) 