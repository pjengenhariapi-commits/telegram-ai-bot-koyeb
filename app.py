import base64
import hmac
import logging
import os
import time
from threading import Thread
from typing import Any

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, jsonify, request


load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
if not WEBHOOK_BASE_URL and os.getenv("KOYEB_PUBLIC_DOMAIN"):
    WEBHOOK_BASE_URL = f"https://{os.environ['KOYEB_PUBLIC_DOMAIN']}"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"
GEMINI_API = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

SYSTEM_PROMPT = (
    "Voce e um assistente util em portugues do Brasil dentro do Telegram. "
    "Responda de forma clara e breve. Quando houver resultados de pesquisa, "
    "baseie-se neles e preserve os links/fontes. Ao receber imagem, descreva "
    "ou leia o texto conforme o pedido do usuario. Nao invente fatos."
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("telegram-ai-bot")
web_app = Flask(__name__)


def telegram(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(
        f"{TELEGRAM_API}/{method}", json=payload or {}, timeout=65
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Erro na API do Telegram"))
    return data["result"]


def download_telegram_file(file_id: str) -> tuple[bytes, str]:
    file_info = telegram("getFile", {"file_id": file_id})
    file_path = file_info["file_path"]
    response = requests.get(f"{TELEGRAM_FILE_API}/{file_path}", timeout=30)
    response.raise_for_status()
    suffix = file_path.rsplit(".", 1)[-1].lower()
    mime = {"png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")
    return response.content, mime


def should_search(prompt: str) -> bool:
    normalized = prompt.lower()
    search_terms = (
        "pesquise", "pesquisar", "procure", "busque", "hoje", "agora",
        "atual", "recente", "noticia", "notícia", "preco", "preço",
        "cotacao", "cotação", "quem é", "qual é", "quando", "onde",
    )
    return "?" in prompt or any(term in normalized for term in search_terms)


def search_web(query: str) -> str:
    try:
        response = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for result in soup.select(".result")[:5]:
            link = result.select_one(".result__a")
            snippet = result.select_one(".result__snippet")
            if link:
                title = link.get_text(" ", strip=True)
                url = link.get("href", "")
                summary = snippet.get_text(" ", strip=True) if snippet else ""
                results.append(f"- {title}\n  {summary}\n  Fonte: {url}")
        return "\n".join(results)
    except requests.RequestException:
        log.warning("A busca publica falhou; continuando sem resultados externos")
        return ""


def ask_gemini(prompt: str, image: tuple[bytes, str] | None = None) -> str:
    if not image and should_search(prompt):
        search_results = search_web(prompt)
        if search_results:
            prompt += (
                "\n\nResultados recentes de busca para apoiar a resposta:\n"
                f"{search_results}\n\nCite os links utilizados e avise se os resultados "
                "nao forem suficientes para confirmar a resposta."
            )
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image:
        image_bytes, mime = image
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1200},
    }
    response = requests.post(
        GEMINI_API,
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return "Nao consegui gerar uma resposta para esse conteudo."
    output_parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(part.get("text", "") for part in output_parts).strip()
    return text or "Nao consegui gerar uma resposta em texto."


def send_long_message(chat_id: int, text: str) -> None:
    while text:
        chunk = text[:4000]
        if len(text) > 4000 and "\n" in chunk:
            chunk = chunk.rsplit("\n", 1)[0]
        telegram("sendMessage", {"chat_id": chat_id, "text": chunk})
        text = text[len(chunk):].lstrip()


def handle_message(message: dict[str, Any]) -> None:
    chat_id = message["chat"]["id"]
    text = (message.get("text") or message.get("caption") or "").strip()

    if text in {"/start", "/help"}:
        send_long_message(
            chat_id,
            "Ola! Envie uma pergunta ou uma foto. Posso pesquisar informacoes "
            "atuais, explicar imagens e ler textos visiveis nelas.",
        )
        return

    image = None
    if message.get("photo"):
        largest_photo = message["photo"][-1]
        image = download_telegram_file(largest_photo["file_id"])
        if not text:
            text = "Descreva esta imagem e transcreva qualquer texto visivel."

    if not text and not image:
        send_long_message(chat_id, "Envie uma pergunta em texto ou uma foto.")
        return

    telegram("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    answer = ask_gemini(text, image)
    send_long_message(chat_id, answer)


def process_update(update: dict[str, Any]) -> None:
    if "message" not in update:
        return
    try:
        handle_message(update["message"])
    except Exception:
        log.exception("Falha ao processar mensagem")
        try:
            send_long_message(
                update["message"]["chat"]["id"],
                "Nao consegui processar agora. Tente novamente em instantes.",
            )
        except Exception:
            log.error("Falha ao enviar a mensagem de erro ao Telegram")


@web_app.get("/")
def health() -> Any:
    return jsonify(status="ok", mode="webhook" if WEBHOOK_BASE_URL else "polling")


@web_app.post("/telegram-webhook")
def webhook() -> Any:
    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not WEBHOOK_SECRET or not hmac.compare_digest(received_secret, WEBHOOK_SECRET):
        return jsonify(ok=False), 403
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return jsonify(ok=False), 400
    Thread(target=process_update, args=(update,), daemon=True).start()
    return jsonify(ok=True)


def configure_webhook() -> None:
    if not WEBHOOK_BASE_URL:
        return
    if not WEBHOOK_SECRET:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET e obrigatorio no modo webhook")
    telegram(
        "setWebhook",
        {
            "url": f"{WEBHOOK_BASE_URL}/telegram-webhook",
            "secret_token": WEBHOOK_SECRET,
            "allowed_updates": ["message"],
            "drop_pending_updates": False,
        },
    )
    log.info("Webhook do Telegram configurado")


def run_polling() -> None:
    log.info("Bot iniciado com o modelo %s", GEMINI_MODEL)
    offset = 0
    while True:
        try:
            updates = telegram(
                "getUpdates",
                {"offset": offset, "timeout": 50, "allowed_updates": ["message"]},
            )
            for update in updates:
                offset = update["update_id"] + 1
                process_update(update)
        except requests.RequestException:
            log.warning("Falha temporaria de rede no loop principal")
            time.sleep(5)
        except Exception:
            log.exception("Erro inesperado no loop principal")
            time.sleep(5)


if WEBHOOK_BASE_URL:
    configure_webhook()


def main() -> None:
    if WEBHOOK_BASE_URL:
        port = int(os.getenv("PORT", "8000"))
        web_app.run(host="0.0.0.0", port=port)
    else:
        run_polling()


if __name__ == "__main__":
    main()
