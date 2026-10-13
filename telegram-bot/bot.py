"""Инженерный Telegram-бот «Джинн».

Что умеет:
  • «Вопросы и ответы» — разделы и вопросы с сайта, ответ по нажатию кнопки;
  • «Инструкции» — PDF открываются прямо в Telegram;
  • «Задать вопрос инженеру» — вопрос пересылается инженеру, ответ инженера
    (ответом на пересланное сообщение) бот возвращает покупателю;
  • ссылки с сайта вида t.me/<бот>?start=manuals или ?start=manual_probe
    сразу открывают нужный раздел.

Без сторонних библиотек: только стандартный Python 3.9+.

Настройки — переменные окружения:
  BOT_TOKEN         токен бота от @BotFather (обязательно)
  ENGINEER_CHAT_ID  чат инженера: id личного чата или группы, куда приходят вопросы
                    (если не задан, бот предлагает позвонить или написать на почту)
  CONTENT_FILE      путь к content.json (по умолчанию рядом с bot.py)
  STATE_FILE        файл для связки «вопрос ↔ покупатель» (по умолчанию state.json)

Запуск:  BOT_TOKEN=... ENGINEER_CHAT_ID=... python bot.py
"""
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("BOT_TOKEN", "")
ENGINEER_CHAT_ID = os.environ.get("ENGINEER_CHAT_ID", "").strip()
CONTENT_FILE = os.environ.get("CONTENT_FILE", os.path.join(HERE, "content.json"))
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(HERE, "state.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dginni-bot")

with open(CONTENT_FILE, encoding="utf-8") as f:
    CONTENT = json.load(f)
FAQ = CONTENT["faq"]
MANUALS = {m["id"]: m for m in CONTENT["manuals"]}


# ---------------------------------------------------------------------------
# Telegram Bot API
# ---------------------------------------------------------------------------
def api(method, **params):
    """Вызов метода Bot API. Сложные параметры передаются JSON-ом."""
    data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
            for k, v in params.items() if v is not None}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=urllib.parse.urlencode(data).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        res = json.load(e)
    if not res.get("ok"):
        log.warning("%s: %s", method, res.get("description"))
    return res


# ---------------------------------------------------------------------------
# Хранилище: какое сообщение у инженера от какого покупателя
# ---------------------------------------------------------------------------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"tickets": {}, "waiting": []}


STATE = load_state()


def save_state():
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STATE, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------------------
# Клавиатуры и тексты
# ---------------------------------------------------------------------------
def kb(rows):
    return {"inline_keyboard": rows}


def btn(text, data=None, url=None):
    return {"text": text, "url": url} if url else {"text": text, "callback_data": data}


BACK_MAIN = [btn("« Главное меню", "main")]

MAIN_TEXT = (
    "Здравствуйте! Это бот инженера «Джинн».\n\n"
    "Здесь ответы на частые вопросы о pH-метрах, pH-контроллерах и блоках управления, "
    "инструкции к приборам и связь с инженером."
)


def main_kb():
    return kb([
        [btn("❓ Вопросы и ответы", "faq")],
        [btn("📄 Инструкции", "manuals")],
        [btn("👷 Задать вопрос инженеру", "ask")],
        [btn("🌐 Сайт и каталог", url=CONTENT["site"])],
    ])


def faq_groups_kb():
    rows = [[btn(g["title"], f"g:{i}")] for i, g in enumerate(FAQ)]
    return kb(rows + [BACK_MAIN])


def faq_items_kb(gi):
    rows = [[btn(it["q"], f"q:{gi}:{qi}")] for qi, it in enumerate(FAQ[gi]["items"])]
    return kb(rows + [[btn("« Разделы", "faq")], BACK_MAIN])


def manuals_kb():
    rows = [[btn("📄 " + m["title"], f"m:{m['id']}")] for m in CONTENT["manuals"]]
    return kb(rows + [BACK_MAIN])


def contacts_text():
    return f"Телефон: {CONTENT['phone']}\nE-mail: {CONTENT['email']}"


# ---------------------------------------------------------------------------
# Действия
# ---------------------------------------------------------------------------
def show(chat_id, text, markup, message_id=None):
    """Показывает экран: правит сообщение с кнопками или отправляет новое."""
    if message_id:
        res = api("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                  parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        if res.get("ok") or "not modified" in str(res.get("description", "")):
            return
    api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
        reply_markup=markup, disable_web_page_preview=True)


def send_manual(chat_id, mid):
    m = MANUALS.get(mid)
    if not m:
        api("sendMessage", chat_id=chat_id, text="Такой инструкции пока нет.", reply_markup=manuals_kb())
        return
    api("sendChatAction", chat_id=chat_id, action="upload_document")
    res = api("sendDocument", chat_id=chat_id, document=m["url"],
              caption=f"Инструкция: {m['title']}", reply_markup=kb([[btn("📄 Другие инструкции", "manuals")], BACK_MAIN]))
    if not res.get("ok"):
        # запасной вариант — ссылка на файл
        api("sendMessage", chat_id=chat_id, text=f"Инструкция: {m['title']}\n{m['url']}",
            reply_markup=kb([BACK_MAIN]))


def start_ask(chat_id, message_id=None):
    if not ENGINEER_CHAT_ID:
        show(chat_id, "Сейчас вопросы инженеру принимаются по телефону и почте.\n\n" + contacts_text(),
             kb([BACK_MAIN]), message_id)
        return
    if chat_id not in STATE["waiting"]:
        STATE["waiting"].append(chat_id)
        save_state()
    show(chat_id, "Напишите вопрос одним сообщением: прибор, задача, что уже пробовали. "
                  "Можно приложить фото. Инженер ответит здесь, в этом чате.",
         kb([[btn("Отмена", "main")]]), message_id)


def forward_to_engineer(msg):
    """Пересылает вопрос покупателя инженеру и запоминает, кому отвечать."""
    chat_id = msg["chat"]["id"]
    user = msg.get("from", {})
    who = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or "Покупатель"
    if user.get("username"):
        who += f" (@{user['username']})"
    head = api("sendMessage", chat_id=ENGINEER_CHAT_ID,
               text=f"❓ Вопрос от {who}\nОтветьте на это сообщение или на пересланное ниже — ответ уйдёт покупателю.")
    fwd = api("copyMessage", chat_id=ENGINEER_CHAT_ID, from_chat_id=chat_id, message_id=msg["message_id"])
    for r in (head, fwd):
        if r.get("ok"):
            STATE["tickets"][str(r["result"]["message_id"])] = chat_id
    if chat_id in STATE["waiting"]:
        STATE["waiting"].remove(chat_id)
    save_state()
    if fwd.get("ok"):
        api("sendMessage", chat_id=chat_id, text="Вопрос отправлен инженеру. Ответ придёт сюда.", reply_markup=main_kb())
    else:
        api("sendMessage", chat_id=chat_id, text="Не удалось отправить вопрос. Свяжитесь с нами:\n" + contacts_text(),
            reply_markup=main_kb())


def engineer_reply(msg):
    """Инженер ответил на сообщение-вопрос — отправляем ответ покупателю."""
    reply_to = msg.get("reply_to_message")
    if not reply_to:
        return
    customer = STATE["tickets"].get(str(reply_to["message_id"]))
    if not customer:
        api("sendMessage", chat_id=msg["chat"]["id"], reply_to_message_id=msg["message_id"],
            text="Не нашёл, кому отвечать: ответьте на сообщение с вопросом.")
        return
    api("sendMessage", chat_id=customer, text="👷 Ответ инженера:")
    res = api("copyMessage", chat_id=customer, from_chat_id=msg["chat"]["id"], message_id=msg["message_id"],
              reply_markup=kb([[btn("Задать ещё вопрос", "ask")], BACK_MAIN]))
    api("sendMessage", chat_id=msg["chat"]["id"], reply_to_message_id=msg["message_id"],
        text="✅ Ответ отправлен." if res.get("ok") else "⚠️ Не удалось отправить ответ.")


def on_start(chat_id, payload):
    if payload == "manuals":
        show(chat_id, "Инструкции к приборам. Нажмите, чтобы открыть в Telegram:", manuals_kb())
    elif payload.startswith("manual_"):
        send_manual(chat_id, payload[len("manual_"):])
    elif payload == "faq":
        show(chat_id, "Выберите раздел:", faq_groups_kb())
    elif payload == "ask":
        start_ask(chat_id)
    else:
        show(chat_id, MAIN_TEXT, main_kb())


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "") or ""
    # сообщения в чате инженера
    if ENGINEER_CHAT_ID and str(chat_id) == ENGINEER_CHAT_ID:
        engineer_reply(msg)
        return
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        on_start(chat_id, parts[1] if len(parts) > 1 else "")
    elif text.startswith("/help") or text.startswith("/menu"):
        show(chat_id, MAIN_TEXT, main_kb())
    elif chat_id in STATE["waiting"] or (ENGINEER_CHAT_ID and not text.startswith("/")):
        # всё, что покупатель пишет боту, считается вопросом инженеру
        forward_to_engineer(msg)
    else:
        show(chat_id, MAIN_TEXT, main_kb())


def handle_callback(cb):
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    mid = msg.get("message_id")
    api("answerCallbackQuery", callback_query_id=cb["id"])
    if chat_id is None:
        return
    if data == "main":
        if chat_id in STATE["waiting"]:
            STATE["waiting"].remove(chat_id)
            save_state()
        show(chat_id, MAIN_TEXT, main_kb(), mid)
    elif data == "faq":
        show(chat_id, "Выберите раздел:", faq_groups_kb(), mid)
    elif data.startswith("g:"):
        gi = int(data[2:])
        show(chat_id, f"<b>{FAQ[gi]['title']}</b>\nВыберите вопрос:", faq_items_kb(gi), mid)
    elif data.startswith("q:"):
        _, gi, qi = data.split(":")
        gi, qi = int(gi), int(qi)
        it = FAQ[gi]["items"][qi]
        show(chat_id, f"<b>{it['q']}</b>\n\n{it['a']}",
             kb([[btn("« К вопросам", f"g:{gi}")], [btn("👷 Спросить инженера", "ask")], BACK_MAIN]), mid)
    elif data == "manuals":
        show(chat_id, "Инструкции к приборам. Нажмите, чтобы открыть в Telegram:", manuals_kb(), mid)
    elif data.startswith("m:"):
        send_manual(chat_id, data[2:])
    elif data == "ask":
        start_ask(chat_id, mid)


def setup_commands():
    api("setMyCommands", commands=[
        {"command": "start", "description": "Главное меню"},
        {"command": "menu", "description": "Вопросы, инструкции, инженер"},
    ])


def run():
    if not TOKEN:
        raise SystemExit("Не задан BOT_TOKEN — получите токен у @BotFather и передайте в переменной окружения.")
    me = api("getMe")
    log.info("Бот запущен: @%s", me.get("result", {}).get("username"))
    setup_commands()
    offset = None
    while True:
        try:
            res = api("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    if "message" in upd:
                        handle_message(upd["message"])
                    elif "callback_query" in upd:
                        handle_callback(upd["callback_query"])
                except Exception:  # одна ошибка не должна останавливать бота
                    log.exception("Ошибка обработки обновления")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log.warning("Нет связи с Telegram: %s — повтор через 5 с", e)
            time.sleep(5)


if __name__ == "__main__":
    run()
