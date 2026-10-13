# Инженерный Telegram-бот «Джинн»

Бот для кнопки «Задать вопрос инженеру» на сайте.

- **Вопросы и ответы** — 17 вопросов по разделам (на сайте их больше нет — только в боте).
- **Инструкции** — PDF открываются прямо в Telegram (pH-метр, пробоотборник).
- **Задать вопрос инженеру** — вопрос приходит инженеру; инженер отвечает
  **ответом (Reply) на сообщение с вопросом**, и бот пересылает ответ покупателю.
- Ссылки с сайта открывают нужный раздел сразу:
  `?start=manuals` — список инструкций, `?start=manual_probe` — инструкция по пробоотборнику,
  `?start=manual_phMetr` — инструкция pH-метра, `?start=faq` — вопросы, `?start=ask` — вопрос инженеру.

Сторонние библиотеки не нужны: только Python 3.9 или новее.

## 1. Создать бота

1. В Telegram откройте **@BotFather** → `/newbot`.
2. Задайте имя (например, «Инженер Джинн») и адрес бота (например, `dginni_engineer_bot`).
3. BotFather пришлёт **токен** — храните его в секрете, в репозиторий не добавляйте.

Если адрес бота отличается от `dginni_ru`, поменяйте ссылки в `index.html`
в объекте `CONFIG`: `engineerBot`, `engineerBotManuals`, `engineerBotProbe`.

## 2. Узнать чат инженера

Вопросы будут приходить в чат, указанный в `ENGINEER_CHAT_ID`. Для «Джинн» это аккаунт
компании **@dginni_ru**:

- **личный чат инженера**: с аккаунта @dginni_ru напишите боту `/start`, затем откройте
  `https://api.telegram.org/bot<ТОКЕН>/getUpdates` и возьмите `chat.id` из последнего сообщения;
- **группа инженеров**: добавьте бота в группу, напишите в ней что-нибудь и возьмите
  `chat.id` (начинается с `-100…`) тем же способом. В настройках бота у BotFather
  отключите Group Privacy (`/setprivacy` → Disable), чтобы бот видел ответы в группе.

Без `ENGINEER_CHAT_ID` бот работает, а на «Задать вопрос инженеру» показывает телефон и почту.

## 3. Запустить

Боту нужен компьютер или сервер, который работает постоянно.

**Проверка на своём компьютере (Windows, PowerShell):**

```powershell
cd telegram-bot
$env:BOT_TOKEN = "токен"
$env:ENGINEER_CHAT_ID = "id чата"
python bot.py
```

## 4. Свой сервер (VPS)

Подойдёт самый простой VPS с Ubuntu или Debian (Timeweb Cloud, Selectel, Beget и т. п.).
Подключитесь к серверу по SSH и выполните по очереди:

```bash
sudo apt update && sudo apt install -y git python3
sudo useradd --system --create-home --home-dir /opt/dginni dginni
sudo -u dginni git clone https://github.com/buzzb94-arch/dginni.git /opt/dginni/repo
sudo ln -s /opt/dginni/repo/telegram-bot /opt/dginni/telegram-bot
sudo cp /opt/dginni/telegram-bot/deploy/dginni-bot.env.example /etc/dginni-bot.env
sudo nano /etc/dginni-bot.env        # впишите BOT_TOKEN и ENGINEER_CHAT_ID, сохраните
sudo chmod 600 /etc/dginni-bot.env
sudo cp /opt/dginni/telegram-bot/deploy/dginni-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dginni-bot
sudo systemctl status dginni-bot     # должно быть active (running)
```

Журнал работы: `sudo journalctl -u dginni-bot -f`.

Обновить бота после изменений в репозитории:

```bash
sudo -u dginni git -C /opt/dginni/repo pull
sudo systemctl restart dginni-bot
```

Для облачных хостингов (Railway, Render и т. п.) в папке есть `Procfile`
(`worker: python bot.py`); токен и id чата задаются в настройках хостинга.

## Обновить вопросы и ответы

Все вопросы, ответы и список инструкций — в файле `content.json`:

- `faq` — разделы (`title`) и вопросы (`q` — вопрос, `a` — ответ). В ответах можно
  использовать `<b>жирный</b>`, `<i>курсив</i>` и `<a href="...">ссылки</a>`;
  символы `<`, `>` и `&` в обычном тексте писать нельзя.
- `manuals` — инструкции: название и ссылка на PDF (файлы лежат в папке `docs/` сайта).

После правки перезапустите бота (на сервере: `sudo systemctl restart dginni-bot`).
