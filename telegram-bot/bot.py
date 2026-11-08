"""Инженерный Telegram-бот «Джинн».

Что умеет:
  • «Вопросы и ответы» — разделы и вопросы с сайта, ответ по нажатию кнопки;
  • «Инструкции» — PDF открываются прямо в Telegram;
  • «Пробоотборник своими руками» — описание, детали, фото сборки и PDF;
  • «Задать вопрос инженеру» — вопрос пересылается инженеру, ответ инженера
    (ответом на пересланное сообщение) бот возвращает покупателю;
  • «Персональные данные» — ссылки на политику и согласие, удаление своих данных;
  • ссылки вида t.me/<бот>?start=manuals, ?start=diy или ?start=manual_probe
    сразу открывают нужный раздел.

Персональные данные (152-ФЗ): вопрос инженеру передаётся только после согласия
покупателя (кнопка «Даю согласие», отметка с датой хранится в STATE_FILE).
Связка «вопрос ↔ покупатель» хранится год, затем удаляется. Бот должен работать
на сервере в России: STATE_FILE содержит персональные данные.

Без сторонних библиотек: только стандартный Python 3.9+.

Настройки — переменные окружения:
  BOT_TOKEN         токен бота от @BotFather (обязательно)
  ENGINEER_CHAT_ID  чат инженера: id личного чата или группы, куда приходят вопросы
                    (если не задан, бот предлагает позвонить или написать на почту)
  CONTENT_FILE      путь к content.json (по умолчанию рядом с bot.py)
  STATE_FILE        согласия и связка «вопрос ↔ покупатель» (по умолчанию state.json)

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
DIY = CONTENT.get("diy")
MANUALS = {m["id"]: m for m in CONTENT["manuals"]}
# документы на сайте открываются по якорю: …/#policy, …/#consent
POLICY_URL = CONTENT["site"] + "#policy"
CONSENT_URL = CONTENT["site"] + "#consent"
TICKET_TTL = 365 * 24 * 3600  # обращения храним год (срок из политики обработки ПДн)


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
# Хранилище: согласия на обработку ПДн и какое сообщение у инженера от какого покупателя
#   consents: {chat_id: "дата согласия"}
#   tickets:  {id сообщения у инженера: {"chat": chat_id покупателя, "ts": время}}
#   waiting:  [chat_id] — нажали «Задать вопрос» и ещё не написали его
# ---------------------------------------------------------------------------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    state.setdefault("tickets", {})
    state.setdefault("waiting", [])
    state.setdefault("consents", {})
    # старый формат связки (просто chat_id) — со сроком хранения от сегодняшнего дня
    now = int(time.time())
    for mid, t in state["tickets"].items():
        if not isinstance(t, dict):
            state["tickets"][mid] = {"chat": t, "ts": now}
    return state


STATE = load_state()


def purge_old_tickets():
    old = time.time() - TICKET_TTL
    for mid in [m for m, t in STATE["tickets"].items() if t["ts"] < old]:
        del STATE["tickets"][mid]


def save_state():
    purge_old_tickets()
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
        *([[btn("🛠 " + DIY["title"], "diy")]] if DIY else []),
        [btn("👷 Задать вопрос инженеру", "ask")],
        [btn("🌐 Сайт и каталог", url=CONTENT["site"])],
        [btn("🔒 Персональные данные", "privacy")],
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


def who_is(user):
    who = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or "Покупатель"
    if user.get("username"):
        who += f" (@{user['username']})"
    return who


DOCS_ROW = [btn("📄 Согласие", url=CONSENT_URL), btn("📄 Политика", url=POLICY_URL)]

CONSENT_TEXT = (
    "Чтобы передать вопрос инженеру, нужно ваше согласие на обработку персональных данных: "
    "имени и имени пользователя в Telegram, текста вопроса и приложенных фото. "
    "Они нужны только для ответа на ваш вопрос.\n\n"
    "Текст согласия и политика обработки персональных данных — по кнопкам ниже."
)


def privacy_text():
    return (
        "<b>Персональные данные</b>\n\n"
        "Бот хранит только то, что нужно, чтобы передать ваш вопрос инженеру и вернуть ответ: "
        "номер вашего чата, дату согласия и связь вопроса с ответом. Связь вопроса с ответом "
        "удаляется через год.\n\n"
        f"Удалить свои данные можно кнопкой ниже или письмом на {CONTENT['email']}."
    )


def privacy_kb():
    return kb([DOCS_ROW, [btn("🗑 Удалить мои данные", "forget")], BACK_MAIN])


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


def diy_kb():
    rows = [[btn(f"📷 Фото сборки ({len(DIY['photos'])})", "diy_photos")]] if DIY.get("photos") else []
    if DIY.get("manual") in MANUALS:
        rows.append([btn("📄 Инструкция по сборке (PDF)", f"m:{DIY['manual']}")])
    return kb(rows + [BACK_MAIN])


def show_diy(chat_id, message_id=None):
    if not DIY:
        show(chat_id, MAIN_TEXT, main_kb(), message_id)
        return
    show(chat_id, DIY["text"], diy_kb(), message_id)


def send_diy_photos(chat_id):
    media = [{"type": "photo", "media": ph["url"], "caption": ph.get("caption", "")} for ph in DIY["photos"][:10]]
    res = api("sendMediaGroup", chat_id=chat_id, media=media)
    if not res.get("ok"):  # запасной вариант — по одному фото
        for ph in DIY["photos"]:
            api("sendPhoto", chat_id=chat_id, photo=ph["url"], caption=ph.get("caption", ""))
    api("sendMessage", chat_id=chat_id, text="Нужна инструкция или помощь со сборкой?", reply_markup=diy_kb())


def start_ask(chat_id, message_id=None):
    if not ENGINEER_CHAT_ID:
        show(chat_id, "Сейчас вопросы инженеру принимаются по телефону и почте.\n\n" + contacts_text(),
             kb([BACK_MAIN]), message_id)
        return
    if str(chat_id) not in STATE["consents"]:
        show(chat_id, CONSENT_TEXT, kb([DOCS_ROW, [btn("✅ Даю согласие", "agree")], [btn("Отмена", "main")]]),
             message_id)
        return
    if chat_id not in STATE["waiting"]:
        STATE["waiting"].append(chat_id)
        save_state()
    show(chat_id, "Напишите вопрос одним сообщением: прибор, задача, что уже пробовали. "
                  "Можно приложить фото. Инженер ответит здесь, в этом чате.",
         kb([[btn("Отмена", "main")]]), message_id)


def agree(chat_id, message_id):
    STATE["consents"][str(chat_id)] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    save_state()
    start_ask(chat_id, message_id)


def forget(chat_id, user, message_id):
    """Удаляет данные покупателя из бота; переписку в чате инженера удаляет инженер."""
    STATE["consents"].pop(str(chat_id), None)
    if chat_id in STATE["waiting"]:
        STATE["waiting"].remove(chat_id)
    tickets = [m for m, t in STATE["tickets"].items() if t["chat"] == chat_id]
    for m in tickets:
        del STATE["tickets"][m]
    save_state()
    if tickets and ENGINEER_CHAT_ID:
        api("sendMessage", chat_id=ENGINEER_CHAT_ID,
            text=f"🗑 {who_is(user)} попросил удалить персональные данные. "
                 "Удалите переписку с ним в этом чате в течение 30 дней.")
    show(chat_id,
         "Готово: бот удалил ваши данные — дату согласия и связь ваших вопросов с ответами. "
         + ("Инженер удалит переписку с вами в своём чате в течение 30 дней. " if tickets else "")
         + "Историю этого чата вы можете очистить сами: меню чата → «Очистить историю».",
         kb([BACK_MAIN]), message_id)


def forward_to_engineer(msg):
    """Пересылает вопрос покупателя инженеру и запоминает, кому отвечать."""
    chat_id = msg["chat"]["id"]
    head = api("sendMessage", chat_id=ENGINEER_CHAT_ID,
               text=f"❓ Вопрос от {who_is(msg.get('from', {}))}\n"
                    "Ответьте на это сообщение или на пересланное ниже — ответ уйдёт покупателю.")
    fwd = api("copyMessage", chat_id=ENGINEER_CHAT_ID, from_chat_id=chat_id, message_id=msg["message_id"])
    for r in (head, fwd):
        if r.get("ok"):
            STATE["tickets"][str(r["result"]["message_id"])] = {"chat": chat_id, "ts": int(time.time())}
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
    ticket = STATE["tickets"].get(str(reply_to["message_id"]))
    if not ticket:
        api("sendMessage", chat_id=msg["chat"]["id"], reply_to_message_id=msg["message_id"],
            text="Не нашёл, кому отвечать: ответьте на сообщение с вопросом.")
        return
    customer = ticket["chat"]
    ticket["ts"] = int(time.time())  # год хранения считаем от последнего ответа
    save_state()
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
    elif payload == "diy":
        show_diy(chat_id)
    elif payload == "ask":
        start_ask(chat_id)
    elif payload == "privacy":
        show(chat_id, privacy_text(), privacy_kb())
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
    elif text.startswith("/privacy"):
        show(chat_id, privacy_text(), privacy_kb())
    elif chat_id in STATE["waiting"] or (ENGINEER_CHAT_ID and not text.startswith("/")):
        # всё, что покупатель пишет боту, считается вопросом инженеру — но только после согласия на обработку ПДн
        if str(chat_id) in STATE["consents"]:
            forward_to_engineer(msg)
        else:
            start_ask(chat_id)
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
    elif data == "diy":
        show_diy(chat_id, mid)
    elif data == "diy_photos" and DIY:
        send_diy_photos(chat_id)
    elif data == "ask":
        start_ask(chat_id, mid)
    elif data == "agree":
        agree(chat_id, mid)
    elif data == "privacy":
        show(chat_id, privacy_text(), privacy_kb(), mid)
    elif data == "forget":
        show(chat_id, "Удалить ваши данные из бота? Вопросы, которые ещё ждут ответа, останутся без ответа.",
             kb([[btn("🗑 Да, удалить", "forget_yes")], [btn("Отмена", "privacy")]]), mid)
    elif data == "forget_yes":
        forget(chat_id, cb.get("from", {}), mid)


def setup_commands():
    api("setMyCommands", commands=[
        {"command": "start", "description": "Главное меню"},
        {"command": "menu", "description": "Вопросы, инструкции, инженер"},
        {"command": "privacy", "description": "Персональные данные и их удаление"},
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
