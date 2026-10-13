"""Собирает content.json для бота из вопросов сайта (FAQ в index.html).

Запуск: python build_content.py faq.json
faq.json — результат JSON.stringify(FAQ) со страницы сайта.
"""
import html
import json
import re
import sys

SITE = "https://buzzb94-arch.github.io/dginni/"


def to_tg_html(src: str) -> str:
    """HTML ответа с сайта → разметка Telegram (b, i, a)."""
    s = re.sub(r">\s+<", "><", src)  # пробелы и переводы строк между тегами
    # таблица «параметр — значение»
    s = re.sub(r"<tr><th[^>]*>(.*?)</th><td>(.*?)</td></tr>", r"• \1 — <b>\2</b>\n", s)
    s = re.sub(r"</?(table|tbody)[^>]*>", "\n", s)
    # нумерованный список
    n = 0
    def li(m):
        nonlocal n
        n += 1
        return f"{n}. {m.group(1)}\n"
    s = re.sub(r"<li>(.*?)</li>", li, s)
    s = re.sub(r"</?ol>", "\n", s)
    # абзацы
    s = s.replace("</p><p>", "\n\n").replace("<p>", "").replace("</p>", "\n")
    # ссылки на разделы сайта → полные адреса
    s = re.sub(r'<a href="#([^"]+)">(.*?)</a>', lambda m: f'<a href="{SITE}#{m.group(1)}">{m.group(2)}</a>', s)
    # заглушки
    s = re.sub(r'<span class="placeholder-mark">.*?</span>',
               "Способы оплаты и доставки уточняйте у инженера: кнопка «Задать вопрос инженеру» или телефон +7 965 571-61-55.", s)
    s = re.sub(r"<(?!/?(b|i|a)\b)[^>]+>", "", s)  # всё остальное — убрать
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def main():
    faq = json.load(open(sys.argv[1], encoding="utf-8"))
    groups = []
    for g in faq:
        groups.append({"title": g["group"], "items": [{"q": q, "a": to_tg_html(a)} for q, a in g["items"]]})
    # таблица автоматов — в ответ про блок высокой мощности
    for g in groups:
        for it in g["items"]:
            if it["q"].startswith("Как подключить блок высокой мощности"):
                it["a"] = ("Через отдельный автоматический выключатель в силовом щите, рассчитанный на подключаемую нагрузку. "
                           "Щит должен выдерживать эту нагрузку.\n\nРекомендуемые автоматы:\n"
                           "• 10 А — до 2000 Вт\n• 16 А — до 3300 Вт\n• 20 А — до 4200 Вт\n"
                           "• 25 А — до 5200 Вт\n• 32 А — до 6800 Вт\n• 40 А — до 8800 Вт\n\n"
                           f'Посчитать нагрузку: <a href="{SITE}#calc">калькулятор на сайте</a>.')
    content = {
        "site": SITE,
        "phone": "+7 965 571-61-55",
        "email": "help@dginni.ru",
        "faq": groups,
        # Инструкции: PDF лежат в репозитории сайта, бот отправляет их по ссылке —
        # Telegram показывает документ прямо в чате.
        "manuals": [
            {"id": "phMetr", "title": "pH-метр «Джинн»", "url": SITE + "docs/ph-metr.pdf", "file": "Инструкция pH-метр Джинн.pdf"},
            {"id": "probe", "title": "Пробоотборник своими руками", "url": SITE + "docs/probootbornik.pdf", "file": "Пробоотборник своими руками.pdf"},
        ],
    }
    json.dump(content, open("content.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("вопросов:", sum(len(g["items"]) for g in groups), "инструкций:", len(content["manuals"]))


if __name__ == "__main__":
    main()
