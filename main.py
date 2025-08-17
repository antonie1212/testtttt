# -*- coding: utf-8 -*-
import os, asyncio, glob, html, re, uuid, csv, pathlib, datetime, time, hashlib
from collections import defaultdict
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaVideo, InputMediaAnimation, InputMediaDocument,
    FSInputFile
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# ==================== Utils ====================
def esc(x): return html.escape(str(x or ""))

def fmt_username(u) -> str:
    return f"@{u.username}" if getattr(u, "username", None) else "(fără username)"

def fmt_username_from_parts(username: str, full_name: str, uid: int) -> str:
    if username:
        return f"@{username}"
    return f"<a href='tg://user?id={uid}'>{esc(full_name or 'developer')}</a>"

def chat_id_to_cid(chat_id: int) -> str:
    # link t.me/c/<cid>/<msg_id> — pentru supergroups: cid = abs(chat_id) - 1000000000000
    n = abs(int(chat_id))
    if str(n).startswith("100"):
        return str(n - 1000000000000)
    return str(n)

def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]

def parse_deadline_to_date(raw: str):
    """Normalizează deadline în ISO (YYYY-MM-DD). Acceptă date și '10 zile'."""
    if not raw: return ""
    raw = raw.strip()
    # zile relative
    m = re.search(r"(\d+)\s*(zi|zile|day|days|дн)", raw.lower())
    if m:
        days = int(m.group(1))
        return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    # formate date
    fmts = ["%Y-%m-%d","%d.%m.%Y","%d/%m/%Y","%d-%m-%Y","%d %m %Y","%d %b %Y","%d %B %Y"]
    for f in fmts:
        try:
            d = datetime.datetime.strptime(raw, f).date()
            return d.isoformat()
        except: pass
    return ""

def human_delta(from_ts_iso: str):
    if not from_ts_iso: return "n/a"
    try:
        start = datetime.datetime.fromisoformat(from_ts_iso)
    except Exception:
        return "n/a"
    delta = datetime.datetime.now() - start
    days = delta.days
    hrs = delta.seconds // 3600
    mins = (delta.seconds % 3600) // 60
    parts = []
    if days: parts.append(f"{days}d")
    if hrs: parts.append(f"{hrs}h")
    if mins and not days: parts.append(f"{mins}m")
    return " ".join(parts) or "0m"

def time_left(deadline_iso: str):
    if not deadline_iso: return "n/a"
    try:
        d = datetime.date.fromisoformat(deadline_iso)
    except Exception:
        return "n/a"
    today = datetime.date.today()
    diff = (d - today).days
    if diff > 0: return f"{diff} zile"
    if diff == 0: return "astăzi"
    return f"{abs(diff)} zile depășit"

CURRENCY_ALIAS = {"LEI":"MDL","MDL":"MDL","EUR":"EUR","USD":"USD","RON":"RON","RUB":"RUB","UAH":"UAH"}

def parse_amount_currency(raw: str):
    if not raw: return None, None
    t = raw.upper().replace(" ", "")
    m = re.search(r"([0-9]+(?:[.,][0-9]+)?)(MDL|LEI|EUR|USD|RON|RUB|UAH)?", t)
    if not m: return None, None
    amount = float(m.group(1).replace(",", "."))
    curr = (m.group(2) or "EUR").upper()
    curr = CURRENCY_ALIAS.get(curr, "EUR")
    return amount, curr

def norm_amount_str(raw: str):
    amt, cur = parse_amount_currency(raw)
    return f"{amt:.0f} {cur}" if amt is not None else ""

def calc_group_budget_text(raw_budget: str) -> str:
    amt, curr = parse_amount_currency(raw_budget)
    if amt is None: return raw_budget or "n/a"
    reduced = round(amt * 0.7)
    return f"~{reduced} {curr}"

now_iso = lambda: datetime.datetime.now().isoformat(timespec="seconds")

# ==================== ENV & Boot ====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)
DEV_GROUP_ID = int(os.getenv("DEV_GROUP_ID", "0") or 0)
ADMIN_COMMISSION_PCT = float(os.getenv("ADMIN_COMMISSION_PCT", "10"))
HASH_SALT = os.getenv("HASH_SALT", "salt")
MANAGER_IDS = {int(x) for x in (os.getenv("MANAGER_IDS","").replace(" ","").split(",") if os.getenv("MANAGER_IDS") else [])}

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN lipsă în .env")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
rt = Router()

# ==================== i18n ====================
LANGS = {
    "ro": {
        "welcome": (
            "👋 Bine ai venit!\n"
            "Prin acest bot poți trimite rapid o cerere pentru orice tip de proiect digital:\n"
            "🎉 Cadouri & Proiecte Speciale — felicitări animate, pagini web aniversare, albume foto online.\n"
            "💼 Servicii pentru Afaceri — website-uri, logo-uri, broșuri, prezentări, formulare de comenzi.\n"
            "🎨 Design & Grafică — postere, bannere, editare foto, tricouri personalizate, ilustrații.\n"
            "💻 Servicii Tehnice & IT — asistență Windows/Linux, recuperare fișiere, optimizare PC, configurări.\n"
            "🌐 Servicii Web & Online — pagini web personale, landing page-uri, portofolii, bloguri.\n"
            "📱 Social Media & Marketing — postări Instagram, cover-uri, șabloane Canva, video scurt.\n"
            "📚 Educație & Freelancing — lecții, ghiduri, suport teme, CV-uri, traduceri.\n\n"
            "✅ Completezi cererea, iar echipa de developeri vede instant în grup proiectul tău.\n"
            "📩 Vei fi contactat direct cu o ofertă personalizată."
        ),
        "pick_lang": "Alege limba pentru a continua:",
        "menu_title": "Alege categoria:",
        "lang_saved": "✅ Limba setată: Română",
        "btn_examples": "🎞️ Vezi exemple",
        "btn_order": "📝 Cere ofertă",
        "btn_ideas": "💡 Idei rapide",
        "btn_back": "⬅️ Înapoi",
        "ask_title": "Trimite un *titlu scurt* pentru proiect (ex: „Landing pentru cafenea”).",
        "ask_desc": "Descrie pe scurt ce ai nevoie (funcții, stil, exemple, linkuri).",
        "ask_budget": "Buget estimativ? (EUR sau MDL; poți scrie și „nu știu”).",
        "ask_deadline": "Termen/dată limită? (ex: 10 zile, 1 septembrie).",
        "ask_contact": "Mod de contact preferat (username, telefon, email).",
        "client_thanks": "Mulțumim! Cererea ta a fost înregistrată ca",
        "ideas_header": "Selectează o idee:",
        "examples_header": "Exemple:",
        "cat": {
            # categorii noi
            "prog_auto": {
                "title": "💻 Programare & Automatizări",
                "desc": "Scripturi Python, web scraping, bots Telegram, integrare API și automatizări cu Excel/PDF.",
                "examples": [
                    "Bot Telegram notificări & comenzi",
                    "Web scraping (prețuri/produse)",
                    "Integrare API (REST/Telegram)",
                    "Automatizare Excel (Pandas/openpyxl)",
                    "Extracție date din PDF"
                ]
            },
            "it_support": {
                "title": "🛠️ IT & Suport",
                "desc": "Instalări, configurări, optimizări PC, Linux/Windows, rețea și audio.",
                "examples": [
                    "Optimizare PC pentru viteză",
                    "Instalare/Configurare Linux",
                    "Setare router / rețea",
                    "Curățare zgomot din audio"
                ]
            },
            "general_services": {
                "title": "📄 Servicii Generale",
                "desc": "Traduceri, introducere date, formatare documente, prezentări, programare postări.",
                "examples": [
                    "CV profesional (PDF)",
                    "Prezentare PowerPoint/Slides",
                    "Broșură digitală (PDF interactiv)",
                    "Programare postări Social Media"
                ]
            },
            "gifts_events": {
                "title": "🎉 Cadouri & Evenimente",
                "desc": "Felicitări digitale, pagini aniversare, invitații, mesaje video personalizate.",
                "examples": [
                    "Felicitare animată 8 Martie",
                    "Felicitare zi de naștere",
                    "Pagină web aniversară / nuntă",
                    "Video cu mesaj & efecte"
                ]
            },
            # existente
            "gifts_special": {
                "title": "🎉 Cadouri & Proiecte Speciale",
                "desc": "Cadouri digitale și proiecte creative personalizate.",
                "examples": [
                    "Felicitare digitală 8 Martie",
                    "Felicitare de zi de naștere",
                    "Pagină web pentru aniversări/nunți",
                    "Personal video cu efecte",
                    "Certificat digital de apreciere",
                    "Album foto online cu efecte 3D"
                ]
            },
            "business_services": {
                "title": "💼 Servicii pentru Afaceri",
                "desc": "Servicii digitale rapide și profesionale pentru afacerea ta.",
                "examples": [
                    "Website de prezentare (24h)",
                    "Website magazin online",
                    "Logo profesional",
                    "Broșură digitală (PDF)",
                    "Anunț publicitar social media",
                    "Prezentare PowerPoint",
                    "Formular online pentru comenzi"
                ]
            },
            "design_graphics": {
                "title": "🎨 Design & Grafică",
                "desc": "Design vizual pentru proiecte personale și comerciale.",
                "examples": [
                    "Design poster pentru evenimente",
                    "Editare poze (retuș, fundal, efecte)",
                    "Banner FB/IG/YouTube",
                    "Design tricouri",
                    "Ilustrație / Caricatură",
                    "Album digital cu animație"
                ]
            },
            "tech_it": {
                "title": "💻 Servicii Tehnice & IT",
                "desc": "Asistență tehnică și soluții IT pentru orice problemă.",
                "examples": [
                    "Windows/Linux (instalare, optimizare)",
                    "Configurare router & internet",
                    "Recuperare fișiere",
                    "Optimizare PC",
                    "Instalare programe (PS, WP)",
                    "Setare server/hosting",
                    "Securitate online"
                ]
            },
            "web_online": {
                "title": "🌐 Servicii Web & Online",
                "desc": "Creare și administrare site-uri și pagini web.",
                "examples": [
                    "Pagină web personală",
                    "Landing page campanie",
                    "Formular de contact",
                    "Portofoliu online",
                    "Blog simplu",
                    "Meniu restaurant"
                ]
            },
            "social_marketing": {
                "title": "📱 Social Media & Marketing",
                "desc": "Conținut optimizat pentru promovare online.",
                "examples": [
                    "Postări personalizate Instagram",
                    "Cover Facebook/YouTube",
                    "Șabloane Canva",
                    "Text publicitar",
                    "Video scurt TikTok/Reels",
                    "GIF-uri personalizate"
                ]
            },
            "education_freelance": {
                "title": "📚 Educație & Freelancing",
                "desc": "Învățare rapidă și suport pentru proiecte.",
                "examples": [
                    "Lecții de bază Photoshop",
                    "Ghid: site gratuit",
                    "Intro programare (Python/JS)",
                    "Ajutor teme IT",
                    "CV profesional",
                    "Traduceri rapide"
                ]
            },
            "website": {
                "title": "🌐 Website / Landing",
                "desc": "Site-uri rapide, landing pages, shop-uri mici.",
                "examples": ["Landing de campanie","Portofoliu one-page","Mic magazin (10-20 produse)"]
            },
            "scripts": {
                "title": "🧩 Script Python / JS",
                "desc": "Automatizări, parsere, mini-dashboard-uri.",
                "examples": ["Parser facturi PDF","Validare formulare JS","Bot Telegram notificări"]
            },
            "netadmin": {
                "title": "🛰️ Network Admin",
                "desc": "Setup server, Nginx, SSL, deploy, backup.",
                "examples": ["VPS + Docker + SSL","CI/CD simplu","Monitorizare & alerte"]
            },
            "other": {
                "title": "✨ Alt serviciu",
                "desc": "Spune ce ai nevoie și îți fac o ofertă.",
                "examples": ["Consultanță arhitectură","Integrare API","Mini-app Telegram"]
            }
        }
    },
    "ru": {
        "welcome": (
            "👋 Добро пожаловать!\n"
            "Быстрый запрос на цифровые проекты: сайты, дизайн, IT‑помощь, соцсети, персональные подарки.\n\n"
            "✅ Оставьте заявку — команда разработчиков сразу видит её в группе.\n"
            "📩 Мы свяжемся с персональным предложением."
        ),
        "pick_lang": "Выберите язык для продолжения:",
        "menu_title": "Выберите категорию:",
        "lang_saved": "✅ Язык установлен: Русский",
        "btn_examples": "🎞️ Примеры",
        "btn_order": "📝 Запросить предложение",
        "btn_ideas": "💡 Быстрые идеи",
        "btn_back": "⬅️ Назад",
        "ask_title": "Отправьте *краткий заголовок* проекта (например: «Лендинг для кофейни»).",
        "ask_desc": "Кратко опишите, что нужно (функции, стиль, примеры, ссылки).",
        "ask_budget": "Ориентировочный бюджет? (EUR или MDL; можно «не знаю»).",
        "ask_deadline": "Срок/дата? (напр.: 10 дней, 2025‑09‑01).",
        "ask_contact": "Предпочтительный контакт (username, телефон, email).",
        "client_thanks": "Спасибо! Ваша заявка зарегистрирована как",
        "ideas_header": "Выберите идею:",
        "examples_header": "Примеры:",
        "cat": {
            "prog_auto": {
                "title": "💻 Программирование и автоматизация",
                "desc": "Скрипты Python, web‑scraping, Telegram‑боты, API, Excel/PDF автоматизация.",
                "examples": ["Telegram‑бот уведомления","Web scraping (цены/товары)","Интеграция API","Автоматизация Excel","Извлечение данных из PDF"]
            },
            "it_support": {
                "title": "🛠️ IT и поддержка",
                "desc": "Установка, настройка, оптимизация ПК, Linux/Windows, сеть и аудио.",
                "examples": ["Оптимизация ПК","Установка/настройка Linux","Настройка роутера/сети","Очистка шума в аудио"]
            },
            "general_services": {
                "title": "📄 Общие услуги",
                "desc": "Переводы, ввод данных, форматирование документов, презентации, планирование постов.",
                "examples": ["Профессиональное резюме (PDF)","Презентация PowerPoint/Slides","PDF‑брошюра","Посты для соцсетей"]
            },
            "gifts_events": {
                "title": "🎉 Подарки и события",
                "desc": "Цифровые открытки, страницы к празднику, приглашения, персональные видео.",
                "examples": ["Открытка к 8 марта","Именная открытка ко дню рождения","Юбилейная/свадебная страница","Видео с посланием"]
            }
        }
    },
    "en": {
        "welcome": (
            "👋 Welcome!\n"
            "Request any digital project fast: websites, design, IT help, social media and personalized gifts.\n\n"
            "✅ Submit your request — our team sees it instantly in the dev group.\n"
            "📩 We’ll contact you with a tailored offer."
        ),
        "pick_lang": "Choose your language to continue:",
        "menu_title": "Pick a category:",
        "lang_saved": "✅ Language set: English",
        "btn_examples": "🎞️ View examples",
        "btn_order": "📝 Request quote",
        "btn_ideas": "💡 Quick ideas",
        "btn_back": "⬅️ Back",
        "ask_title": "Send a *short title* (e.g. “Landing for a coffee shop”).",
        "ask_desc": "Briefly describe what you need (features, style, examples, links).",
        "ask_budget": "Estimated budget? (EUR or MDL; you may write “not sure”).",
        "ask_deadline": "Deadline/date? (e.g. 10 days, 2025‑09‑01).",
        "ask_contact": "Preferred contact (username, phone, email).",
        "client_thanks": "Thanks! Your request has been registered as",
        "ideas_header": "Pick an idea:",
        "examples_header": "Examples:",
        "cat": {
            "prog_auto": {
                "title": "💻 Programming & Automation",
                "desc": "Python scripts, web scraping, Telegram bots, API integration, Excel/PDF automation.",
                "examples": ["Telegram bot alerts","Web scraping (prices/products)","API integration","Excel automation","PDF data extraction"]
            },
            "it_support": {
                "title": "🛠️ IT & Support",
                "desc": "Installations, configuration, PC optimization, Linux/Windows, networking & audio.",
                "examples": ["PC performance tune‑up","Linux install/config","Router/network setup","Audio noise reduction"]
            },
            "general_services": {
                "title": "📄 General Services",
                "desc": "Translations, data entry, document formatting, presentations, social scheduling.",
                "examples": ["Professional CV (PDF)","PowerPoint/Slides deck","Interactive PDF brochure","Social media scheduling"]
            },
            "gifts_events": {
                "title": "🎉 Gifts & Events",
                "desc": "Digital greetings, anniversary pages, invites, personalized video messages.",
                "examples": ["Women’s Day e‑card","Birthday personalized e‑card","Anniversary/Wedding web page","Video message with effects"]
            }
        }
    }
}

USER_LANG = {}
def get_lang(user_id) -> str:
    code = USER_LANG.get(user_id, "ro")
    return code if code in LANGS else "ro"
def set_lang(user_id, code: str):
    USER_LANG[user_id] = code if code in LANGS else "ro"

def language_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇴 Română", callback_data="set_lang:ro")
    kb.button(text="🇷🇺 Русский", callback_data="set_lang:ru")
    kb.button(text="🇬🇧 English", callback_data="set_lang:en")
    kb.adjust(3); return kb.as_markup()

# media dirs pentru preview (opțional)
MEDIA_DIRS = {
    "website":"media/website","scripts":"media/scripts","netadmin":"media/netadmin","other":"media/other"
}

# Ordinea în meniu – noile categorii + restul
CATEGORY_ORDER = [
    "prog_auto","it_support","general_services","gifts_events",
    "gifts_special","business_services","design_graphics","tech_it",
    "web_online","social_marketing","education_freelance",
    "website","scripts","netadmin","other"
]

# 💡 Idei rapide (sub‑categorii)
IDEAS = {
    "ro": {
        "prog_auto": [
            {"id":"bot_meteo","title":"☀️ Bot Telegram meteo zilnic","desc":"Trimite prognoza zilnic la o oră setată.","price":"300–500 MDL"},
            {"id":"price_watch","title":"🔔 Monitorizare preț produse","desc":"Alerte când scade prețul pe un site.","price":"300–600 MDL"},
            {"id":"excel_auto","title":"📊 Automatizare Excel","desc":"Grafice și calcule automate din CSV/Excel.","price":"300–500 MDL"},
            {"id":"pdf_extract","title":"📄 Extracție date din PDF","desc":"Scoate tabele/valori și exportă în Excel.","price":"300–600 MDL"},
        ],
        "it_support": [
            {"id":"pc_tune","title":"🧹 Optimizare PC","desc":"Curățare, startup, drivere, update‑uri.","price":"200–300 MDL"},
            {"id":"linux_setup","title":"🐧 Instalare/Config Linux","desc":"Ubuntu/Debian/Mint + pachete de bază.","price":"300–500 MDL"},
            {"id":"obs_cfg","title":"🎥 Config OBS streaming","desc":"Scene, microfon, bitrate, captură.","price":"200–350 MDL"},
            {"id":"audio_clean","title":"🎧 Curățare zgomot audio","desc":"Reducere zgomot, normalizare volum.","price":"200–400 MDL"},
        ],
        "general_services": [
            {"id":"cv_pdf","title":"📄 CV profesional (PDF)","desc":"Design curat, lizibil, export PDF.","price":"150–300 MDL"},
            {"id":"ppt_pitch","title":"📈 Prezentare business","desc":"Template modern + iconițe + grafice.","price":"200–500 MDL"},
            {"id":"pdf_brochure","title":"📘 Broșură PDF interactivă","desc":"Link‑uri, cuprins, butoane.","price":"300–500 MDL"},
            {"id":"sm_posts","title":"📅 Postări Social Media (x5)","desc":"Pregătite de publicare cu text & imagini.","price":"100–300 MDL"},
        ],
        "gifts_events": [
            {"id":"ecard_8m","title":"🌷 Felicitare 8 Martie","desc":"Text, poze, muzică – link sau video.","price":"150–250 MDL"},
            {"id":"bday_card","title":"🎂 Felicitare „La mulți ani”","desc":"Efecte + nume personalizat.","price":"150–300 MDL"},
            {"id":"anniv_page","title":"💍 Pagină web aniversară","desc":"Poze, text, melodie, link unic.","price":"300–600 MDL"},
            {"id":"video_msg","title":"📹 Mesaj video personalizat","desc":"Clip scurt editat cu efecte.","price":"250–400 MDL"},
        ],
    },
    "ru": {
        "prog_auto": [
            {"id":"bot_meteo","title":"☀️ Telegram‑бот погода","desc":"Ежедневный прогноз в заданный час.","price":"300–500 MDL"},
            {"id":"price_watch","title":"🔔 Мониторинг цен","desc":"Оповещения при снижении цены.","price":"300–600 MDL"},
        ],
        "it_support": [
            {"id":"pc_tune","title":"🧹 Оптимизация ПК","desc":"Чистка, автозапуск, драйверы.","price":"200–300 MDL"},
        ],
        "general_services": [
            {"id":"cv_pdf","title":"📄 Резюме (PDF)","desc":"Чистый, читаемый дизайн.","price":"150–300 MDL"},
        ],
        "gifts_events": [
            {"id":"ecard_8m","title":"🌷 Открытка к 8 марта","desc":"Текст, фото, музыка.","price":"150–250 MDL"},
        ],
    },
    "en": {
        "prog_auto": [
            {"id":"bot_meteo","title":"☀️ Telegram weather bot","desc":"Daily forecast at a set time.","price":"300–500 MDL"},
            {"id":"price_watch","title":"🔔 Price watch script","desc":"Alerts when price drops.","price":"300–600 MDL"},
        ],
        "it_support": [
            {"id":"pc_tune","title":"🧹 PC tune‑up","desc":"Cleanup, startup, drivers.","price":"200–300 MDL"},
        ],
        "general_services": [
            {"id":"cv_pdf","title":"📄 Professional CV (PDF)","desc":"Clean, readable design.","price":"150–300 MDL"},
        ],
        "gifts_events": [
            {"id":"ecard_8m","title":"🌷 Women’s Day e‑card","desc":"Text, photos, music.","price":"150–250 MDL"},
        ],
    }
}

# ==================== Mini‑CRM CSV ====================
LOG_PATH = pathlib.Path("orders_log.csv")
FIELDNAMES = [
    "ts","req_id","user_id","username","full_name",
    "category","title","desc","budget_raw",
    "deadline","deadline_iso","contact",
    "status","assigned_dev_ids","started_ts","notes",
    "topic_id","topic_link"
]

def load_log():
    rows=[]
    if LOG_PATH.exists():
        with LOG_PATH.open("r", newline="", encoding="utf-8") as f:
            r=csv.DictReader(f); rows=list(r)
    return rows

def save_log(rows):
    with LOG_PATH.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=FIELDNAMES); w.writeheader()
        for row in rows:
            base={k:row.get(k,"") for k in FIELDNAMES}; w.writerow(base)

def log_order(row: dict):
    rows=load_log()
    idx=next((i for i,x in enumerate(rows) if x.get("req_id")==row.get("req_id")), None)
    if idx is None: rows.append({k:"" for k in FIELDNAMES}|row)
    else: rows[idx].update(row)
    save_log(rows)

def update_order(req_id: str, **fields):
    rows=load_log()
    idx=next((i for i,x in enumerate(rows) if x.get("req_id")==req_id), None)
    if idx is None: return False
    rows[idx].update({k:("" if v is None else str(v)) for k,v in fields.items()})
    save_log(rows); return True

def get_order(req_id: str):
    for r in load_log():
        if r.get("req_id")==req_id: return r
    return None

# ===== Earnings (ledger) =====
EARN_PATH = pathlib.Path("earnings_log.csv")
EARN_FIELDS = ["ts","req_id","dev_id","dev_username","amount","currency","note"]
def append_earning(req_id: str, dev_id: str, dev_username: str, amount: float, currency: str, note: str):
    EARN_PATH.touch(exist_ok=True)
    write_header = EARN_PATH.stat().st_size == 0
    with EARN_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EARN_FIELDS)
        if write_header: w.writeheader()
        w.writerow({
            "ts": now_iso(),"req_id": req_id,"dev_id": str(dev_id),
            "dev_username": dev_username or "","amount": f"{amount:.2f}",
            "currency": currency or "EUR","note": note or ""
        })

def dev_totals(dev_id: int):
    total=0.0; currency="EUR"; finished=0
    if not EARN_PATH.exists(): return 0.0, "EUR", 0
    with EARN_PATH.open("r", newline="", encoding="utf-8") as f:
        r=csv.DictReader(f)
        for row in r:
            if row.get("dev_id")==str(dev_id):
                try: total += float(row.get("amount","0") or 0)
                except: pass
                currency = row.get("currency","EUR"); finished += 1
    return total, currency, finished

# ===== Role & Permissions =====
OWNER_ID = ADMIN_CHAT_ID
ROLES = {"OWNER":{OWNER_ID}, "MANAGER":MANAGER_IDS, "DEV":set()}  # DEV implicit restul
def is_owner(uid): return uid in ROLES["OWNER"]
def is_manager(uid): return is_owner(uid) or uid in ROLES["MANAGER"]
def can_payout(uid): return is_owner(uid)  # doar OWNER pentru confirmare plăți

def admin_totals(period_days: int | None = None):
    by_cur = {}
    rows_count = 0
    if not EARN_PATH.exists():
        return by_cur, rows_count
    cutoff = None
    if period_days:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=period_days)
    with EARN_PATH.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if (row.get("dev_id") or "").upper() != "ADMIN":
                continue
            ts = row.get("ts") or ""
            if cutoff:
                try:
                    dt = datetime.datetime.fromisoformat(ts)
                    if dt < cutoff:
                        continue
                except:
                    pass
            cur = (row.get("currency") or "EUR").upper()
            try:
                amt = float(row.get("amount") or 0)
            except:
                amt = 0.0
            by_cur[cur] = by_cur.get(cur, 0.0) + amt
            rows_count += 1
    return by_cur, rows_count

# ===== In‑Memory =====
LAST_REQ = {}
def allowed(user_id, window=30):
    now=time.time()
    if now - LAST_REQ.get(user_id, 0) < window: return False
    LAST_REQ[user_id]=now; return True

REQ_INDEX = {}             # {req_id: {..., assigned_dev_ids:set(), roles:{dev_id:{role,pct}}, topic_id:int, topic_link:str}}
CLAIMS = defaultdict(dict) # {req_id: {dev_id:{username,full_name}}}
PAYOUT_CTX = {}            # {admin_id: {...}}

# ==================== Meniuri ====================
def main_menu_kb(user_id: int):
    L = LANGS[get_lang(user_id)]
    rows = []
    for pid in CATEGORY_ORDER:
        # folosește fallback la RO dacă lipsește traducerea în limba curentă
        cat = (LANGS[get_lang(user_id)]["cat"].get(pid)
               or LANGS["ro"]["cat"].get(pid))
        if not cat: 
            continue
        rows.append([InlineKeyboardButton(text=cat["title"], callback_data=f"cat:{pid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def category_kb(pid: str, user_id: int):
    L = LANGS[get_lang(user_id)]
    kb = InlineKeyboardBuilder()
    kb.button(text=L["btn_examples"], callback_data=f"examples:{pid}")
    kb.button(text=L["btn_ideas"],    callback_data=f"ideas:{pid}")
    kb.button(text=L["btn_order"],    callback_data=f"order:{pid}")
    kb.button(text=L["btn_back"],     callback_data="back:menu")
    kb.adjust(1)
    return kb.as_markup()

def ideas_kb(pid: str, user_id: int):
    lang = get_lang(user_id)
    items = IDEAS.get(lang, {}).get(pid, [])
    kb = InlineKeyboardBuilder()
    for it in items:
        kb.button(text=f"• {it['title']}", callback_data=f"idea:{pid}:{it['id']}")
    kb.button(text="⬅️ Înapoi", callback_data=f"cat:{pid}")
    kb.adjust(1)
    return kb.as_markup()

# ==================== FSM-uri ====================
class OrderForm(StatesGroup):
    waiting_title   = State()
    waiting_desc    = State()
    waiting_budget  = State()
    waiting_deadline= State()
    waiting_contact = State()

class DevComment(StatesGroup):
    waiting_note = State()

class AdminPayout(StatesGroup):
    picking = State()

class AskPercent(StatesGroup):
    waiting_pct = State()

# ==================== Start & limbă ====================
@rt.message(Command("start"))
async def cmd_start(m: Message):
    text = (
        "🇷🇴 " + LANGS["ro"]["welcome"] + "\n\n"
        "🇷🇺 " + LANGS["ru"]["welcome"] + "\n\n"
        "🇬🇧 " + LANGS["en"]["welcome"] + "\n\n"
        "— — —\n"
        f"🌐 {LANGS['ro']['pick_lang']}\n"
        f"🌐 {LANGS['ru']['pick_lang']}\n"
        f"🌐 {LANGS['en']['pick_lang']}"
    )
    await m.answer(text, reply_markup=language_kb())

@rt.callback_query(F.data.startswith("set_lang:"))
async def set_language(cq: CallbackQuery):
    code = cq.data.split(":")[1]
    set_lang(cq.from_user.id, code)
    L = LANGS[get_lang(cq.from_user.id)]
    await cq.message.edit_text(f"{L['lang_saved']}\n\n{L['menu_title']}")
    await cq.message.answer(L["menu_title"], reply_markup=main_menu_kb(cq.from_user.id))
    await cq.answer()

@rt.message(Command("check_forum"))
async def check_forum(m: Message):
    try:
        chat = await bot.get_chat(m.chat.id)
        me = await bot.get_chat_member(m.chat.id, (await bot.get_me()).id)
        is_forum = getattr(chat, "is_forum", False)
        chat_type = getattr(chat, "type", "")
        perms = getattr(me, "can_manage_topics", None)
        await m.answer(
            "🧪 Forum check:\n"
            f"• chat.type: {chat_type}\n"
            f"• chat.is_forum: {is_forum}\n"
            f"• bot.can_manage_topics: {perms}\n\n"
            "Dacă is_forum=False → activează Topics în setările grupului.\n"
            "Dacă can_manage_topics=False → fă botul admin cu dreptul „Manage Topics”."
        )
    except Exception as e:
        await m.answer(f"Eroare la check_forum: {e}")

@rt.message(Command("id_here"))
async def id_here(m: Message):
    await m.answer(
        f"chat.id = {m.chat.id}\n"
        f"chat.type = {m.chat.type}\n"
        f"message_thread_id = {getattr(m, 'message_thread_id', None)}"
    )

# ==================== Catalog flow ====================
@rt.callback_query(F.data == "back:menu")
async def back_menu(cq: CallbackQuery):
    L = LANGS[get_lang(cq.from_user.id)]
    await cq.message.edit_text(L["menu_title"], reply_markup=main_menu_kb(cq.from_user.id))
    await cq.answer()

@rt.callback_query(F.data.startswith("cat:"))
async def open_category(cq: CallbackQuery):
    pid = cq.data.split(":")[1]
    lang = get_lang(cq.from_user.id)
    L = LANGS[lang]
    cat = (L["cat"].get(pid) or LANGS["ro"]["cat"].get(pid))
    if not cat:
        return await cq.answer("Category unavailable.", show_alert=True)
    header = L.get("examples_header","Examples:")
    text = f"**{cat['title']}**\n{cat['desc']}\n\n{header}\n• " + "\n• ".join(cat["examples"])
    await cq.message.edit_text(text, parse_mode="Markdown", reply_markup=category_kb(pid, cq.from_user.id))
    await cq.answer()

@rt.callback_query(F.data.startswith("ideas:"))
async def open_ideas(cq: CallbackQuery):
    pid = cq.data.split(":")[1]
    lang = get_lang(cq.from_user.id)
    L = LANGS[lang]
    cat = (L["cat"].get(pid) or LANGS["ro"]["cat"].get(pid))
    if not cat:
        return await cq.answer("Category unavailable.", show_alert=True)
    items = IDEAS.get(lang, {}).get(pid, [])
    if not items:
        return await cq.answer("Nu avem încă idei aici.", show_alert=True)
    text = f"💡 <b>{cat['title']}</b>\n{cat['desc']}\n\n{L.get('ideas_header','Ideas:')}"
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=ideas_kb(pid, cq.from_user.id))
    await cq.answer()

@rt.callback_query(F.data.startswith("idea:"))
async def open_one_idea(cq: CallbackQuery):
    _, pid, idea_id = cq.data.split(":")
    lang = get_lang(cq.from_user.id)
    L = LANGS[lang]
    items = IDEAS.get(lang, {}).get(pid, [])
    idea = next((x for x in items if x["id"] == idea_id), None)
    if not idea:
        return await cq.answer("Ideea nu mai este disponibilă.", show_alert=True)
    text = (
        f"💡 <b>{idea['title']}</b>\n"
        f"{idea['desc']}\n"
        f"💰 <i>Preț orientativ:</i> <b>{idea['price']}</b>\n\n"
        "Dacă îți place, cere ofertă pentru această categorie."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Cere ofertă", callback_data=f"order:{pid}")
    kb.button(text="⬅️ Înapoi la idei", callback_data=f"ideas:{pid}")
    kb.adjust(1)
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await cq.answer()

@rt.callback_query(F.data.startswith("examples:"))
async def show_examples(cq: CallbackQuery):
    pid = cq.data.split(":")[1]
    lang = get_lang(cq.from_user.id)
    L = LANGS[lang]
    media_dir = MEDIA_DIRS.get(pid)
    if not media_dir:
        return await cq.answer("No media configured.", show_alert=True)

    paths = sorted(glob.glob(os.path.join(media_dir, "*")))
    if not paths:
        await cq.answer("No media yet. Check back soon.", show_alert=True)
        return

    cat_title = (L["cat"].get(pid, {}) or LANGS["ro"]["cat"].get(pid, {})).get("title") or pid.title()

    media = []
    for i, p in enumerate(paths[:10]):  # Telegram acceptă max 10 într-un album
        ext = os.path.splitext(p)[1].lower()
        cap = cat_title if i == 0 else None
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            media.append(InputMediaPhoto(media=FSInputFile(p), caption=cap))
        elif ext in (".mp4", ".mov", ".m4v"):
            media.append(InputMediaVideo(media=FSInputFile(p), caption=cap))
        elif ext in (".gif",):
            media.append(InputMediaAnimation(media=FSInputFile(p), caption=cap))
        elif ext in (".pdf",):
            media.append(InputMediaDocument(media=FSInputFile(p), caption=cap))
        else:
            continue

    if media:
        await bot.send_media_group(chat_id=cq.message.chat.id, media=media)

    await cq.message.answer(L["menu_title"], reply_markup=category_kb(pid, cq.from_user.id))
    await cq.answer()

# ==================== Validare buget/deadline ====================
def validate_budget_text(txt: str) -> str:
    return norm_amount_str(txt)

def validate_deadline_text(txt: str) -> str:
    return parse_deadline_to_date(txt or "")

# ==================== Cerere ofertă ====================
@rt.callback_query(F.data.startswith("order:"))
async def start_order(cq: CallbackQuery, state: FSMContext):
    pid = cq.data.split(":")[1]
    uid = cq.from_user.id
    lang = get_lang(uid)
    L = LANGS[lang]
    # titlul categoriei în limba curentă (fallback la RO)
    cat_title = (L["cat"].get(pid, {}) or LANGS["ro"]["cat"].get(pid, {})).get("title", pid.title())
    await state.update_data(category_id=pid, category_title=cat_title)
    await state.set_state(OrderForm.waiting_title)
    await cq.message.answer(f"📝 **{cat_title}**\n{L['ask_title']}", parse_mode="Markdown")
    await cq.answer()

@rt.message(OrderForm.waiting_title)
async def order_title(m: Message, state: FSMContext):
    L = LANGS[get_lang(m.from_user.id)]
    await state.update_data(title=(m.text or "").strip())
    await state.set_state(OrderForm.waiting_desc)
    await m.answer(L["ask_desc"])

@rt.message(OrderForm.waiting_desc)
async def order_desc(m: Message, state: FSMContext):
    L = LANGS[get_lang(m.from_user.id)]
    await state.update_data(desc=(m.text or "").strip())
    await state.set_state(OrderForm.waiting_budget)
    await m.answer(L["ask_budget"])

@rt.message(OrderForm.waiting_budget)
async def order_budget(m: Message, state: FSMContext):
    L = LANGS[get_lang(m.from_user.id)]
    norm = validate_budget_text(m.text or "")
    if not norm:
        return await m.answer("❗ Format buget invalid. Exemple: `300 EUR`, `500 MDL`.", parse_mode="Markdown")
    await state.update_data(budget=norm)
    await state.set_state(OrderForm.waiting_deadline)
    await m.answer(L["ask_deadline"])

@rt.message(OrderForm.waiting_deadline)
async def order_deadline(m: Message, state: FSMContext):
    L = LANGS[get_lang(m.from_user.id)]
    iso = validate_deadline_text(m.text or "")
    if not iso:
        return await m.answer("❗ Termen invalid. Exemple: `10 zile` sau `2025-09-01`.")
    await state.update_data(deadline=m.text.strip(), deadline_iso=iso)
    await state.set_state(OrderForm.waiting_contact)
    await m.answer(L["ask_contact"])

@rt.message(OrderForm.waiting_contact)
async def order_contact(m: Message, state: FSMContext):
    user_id = m.from_user.id
    L = LANGS[get_lang(user_id)]
    if not allowed(user_id):
        return await m.answer("Aștepți puțin înainte de o nouă cerere, te rog. ⏳")

    await state.update_data(contact=(m.text or "").strip())
    data = await state.get_data()
    await state.clear()

    req_id = uuid.uuid4().hex[:8].upper()
    uname = fmt_username(m.from_user)
    uid = m.from_user.id
    full_name = m.from_user.full_name

    buget_real = data.get('budget') or "n/a"
    buget_grup = calc_group_budget_text(buget_real)
    client_hash = sha1_hex(str(uid) + os.getenv("HASH_SALT","salt"))

    # Log + index
    log_order({
        "ts": now_iso(), "req_id": req_id,
        "user_id": str(uid), "username": m.from_user.username or "", "full_name": full_name,
        "category": data.get('category_title') or "",
        "title": data.get('title') or "", "desc": data.get('desc') or "",
        "budget_raw": buget_real or "",
        "deadline": data.get('deadline') or "", "deadline_iso": data.get('deadline_iso') or "",
        "contact": data.get('contact') or "", "status": "nou",
        "assigned_dev_ids": "", "started_ts": "", "notes": "", "topic_id":"", "topic_link":""
    })

    REQ_INDEX[req_id] = {
        "user_id": uid, "username": m.from_user.username or "", "full_name": full_name,
        "category": data.get('category_title') or "", "title": data.get('title') or "",
        "desc": data.get('desc') or "", "budget_raw": buget_real or "",
        "deadline": data.get('deadline') or "", "deadline_iso": data.get('deadline_iso') or "",
        "contact": data.get('contact') or "", "status": "nou",
        "assigned_dev_ids": set(), "roles": {}, "started_ts": "", "notes": "",
        "topic_id": 0, "topic_link": ""
    }

    # 1) DM client + buton Contact admin
    contact_admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📬 Contact admin", url=f"tg://user?id={ADMIN_CHAT_ID}")]
    ])
    await m.answer(f"{L['client_thanks']} <b>#{req_id}</b>. ✅", parse_mode="HTML", reply_markup=contact_admin_kb)
    summary_client = (
        "✅ <b>Detalii cerere</b>\n"
        f"🆔 ID: <b>{req_id}</b>\n"
        f"📦 {esc(REQ_INDEX[req_id]['category'])}\n"
        f"📝 {esc(REQ_INDEX[req_id]['title'])}\n"
        f"✍️ {esc(REQ_INDEX[req_id]['desc'])}\n"
        f"💰 {esc(buget_real)}\n"
        f"⏳ {esc(REQ_INDEX[req_id]['deadline'])}\n"
    )
    await m.answer(summary_client, parse_mode="HTML")

    # 2) Creează topic în grup (forum)
    topic_id = 0; topic_link = ""
    try:
        if DEV_GROUP_ID:
            topic_title = f"#{req_id} – {REQ_INDEX[req_id]['title'][:40]}"
            ft = await bot.create_forum_topic(chat_id=DEV_GROUP_ID, name=topic_title)
            topic_id = ft.message_thread_id
            cid = chat_id_to_cid(DEV_GROUP_ID)
            topic_link = f"https://t.me/c/{cid}/{topic_id}"
            REQ_INDEX[req_id]["topic_id"] = topic_id
            REQ_INDEX[req_id]["topic_link"] = topic_link
            update_order(req_id, topic_id=str(topic_id), topic_link=topic_link)
    except TelegramBadRequest as e:
        print("[W] create_forum_topic:", e)

    # 3) Mesaj în topic pentru devs
    dev_summary = (
        "📌 <b>Cerere nouă</b>\n"
        f"🆔 Cerere: <b>{req_id}</b>\n"
        f"👤 Client: hash <code>{client_hash}</code>\n"
        f"💰 Buget : <b>{esc(buget_grup)}</b>\n"
        f"📦 Categoria: {esc(REQ_INDEX[req_id]['category'])}\n"
        f"📝 Titlu: {esc(REQ_INDEX[req_id]['title'])}\n"
        f"✍️ Descriere: {esc(REQ_INDEX[req_id]['desc'])}\n"
        f"⏳ Termen: {esc(REQ_INDEX[req_id]['deadline'])}\n"
        "<i>Contactul direct cu clientul îl face doar adminul.</i>"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Vreau acest proiect", callback_data=f"claim:{req_id}")
    if topic_link:
        kb.button(text="💬 Deschide discuția", url=topic_link)
    kb.adjust(1)

    try:
        if DEV_GROUP_ID:
            if topic_id:
                await bot.send_message(DEV_GROUP_ID, dev_summary, parse_mode="HTML", reply_markup=kb.as_markup(), message_thread_id=topic_id)
            else:
                await bot.send_message(DEV_GROUP_ID, dev_summary, parse_mode="HTML", reply_markup=kb.as_markup())
    except Exception as e:
        print("[E] send to group:", repr(e))

    # 4) Admin (buget real)
    admin_summary = (
        "🔒 <b>Detalii cerere (ADMIN)</b>\n"
        f"🆔 ID: <b>{req_id}</b>\n"
        f"👤 Client: {esc(uname)} (ID: <code>{uid}</code>)\n"
        f"💰 Buget REAL: <b>{esc(buget_real)}</b>\n"
        f"📦 Categoria: {esc(REQ_INDEX[req_id]['category'])}\n"
        f"📝 Titlu: {esc(REQ_INDEX[req_id]['title'])}\n"
        f"⏳ Termen: {esc(REQ_INDEX[req_id]['deadline'])} ({REQ_INDEX[req_id]['deadline_iso']})\n"
        f"🔗 Topic: {topic_link or 'n/a'}"
    )
    if ADMIN_CHAT_ID:
        await bot.send_message(ADMIN_CHAT_ID, admin_summary, parse_mode="HTML", disable_web_page_preview=True)

# ==================== Claim ====================
@rt.callback_query(F.data.startswith("claim:"))
async def on_claim(callback: CallbackQuery):
    req_id = callback.data.split(":", 1)[1]
    info = REQ_INDEX.get(req_id)
    dev = callback.from_user
    if not info:
        return await callback.answer("Cererea nu mai este înregistrată.", show_alert=True)

    CLAIMS[req_id][dev.id] = {"username": dev.username or "", "full_name": dev.full_name or ""}

    if ADMIN_CHAT_ID:
        dev_name = fmt_username(dev)
        text_admin = (
            "📥 <b>Claim proiect</b>\n"
            f"🆔 Cerere: <b>{req_id}</b>\n"
            f"👨‍💻 Dev: {esc(dev_name)} (ID: <code>{dev.id}</code>)"
        )
        await bot.send_message(ADMIN_CHAT_ID, text_admin, parse_mode="HTML")

    await callback.answer("Interes înregistrat. Adminul decide asignarea.")

# ==================== Admin Panel (doar OWNER/MANAGER) ====================
def is_admin(uid): return is_manager(uid)

@rt.message(Command("admin"))
async def admin_menu(m: Message):
    if m.chat.type != "private" or not is_admin(m.from_user.id):
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🧩 Assign",  callback_data="adm:assign")
    kb.button(text="➕ AddDev",   callback_data="adm:adddev")
    kb.button(text="🎯 Set Role/Pct", callback_data="adm:role")
    kb.button(text="📊 Status",   callback_data="adm:status")
    kb.button(text="🧾 Details",  callback_data="adm:details")
    kb.button(text="📜 Active",   callback_data="adm:active")
    kb.button(text="🗒️ Comment", callback_data="adm:comment")
    kb.button(text="📤 Export",   callback_data="adm:export")
    kb.button(text="💰 Admin funds", callback_data="adm:funds")
    kb.adjust(2)
    await m.answer("👑 Admin panel:", reply_markup=kb.as_markup())

@rt.callback_query(F.data == "adm:funds")
async def adm_funds(cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        return await cq.answer("Doar admin/manager.", show_alert=True)

    all_time, n_all = admin_totals()
    last30, n_30 = admin_totals(period_days=30)

    def fmt_totals(d):
        if not d:
            return "—"
        return ", ".join([f"{cur} {amt:.2f}" for cur, amt in d.items()])

    txt = (
        "💰 <b>Admin funds (comisioane)</b>\n"
        f"• All‑time: {fmt_totals(all_time)}  (rows: {n_all})\n"
        f"• Ultimele 30 zile: {fmt_totals(last30)}  (rows: {n_30})\n\n"
        "Pentru CSV doar cu comisioanele admin folosește: <code>/export_admin</code>"
    )
    await cq.message.edit_text(txt, parse_mode="HTML")
    await cq.answer()

@rt.message(Command("export_admin"))
async def export_admin(m: Message):
    if not is_admin(m.from_user.id):
        return
    if not EARN_PATH.exists():
        return await m.answer("Nu există încă înregistrări de comision.")
    out = pathlib.Path("export_admin_commissions.csv")
    with EARN_PATH.open("r", newline="", encoding="utf-8") as fin, out.open("w", newline="", encoding="utf-8") as fout:
        r = csv.DictReader(fin)
        w = csv.DictWriter(fout, fieldnames=EARN_FIELDS)
        w.writeheader()
        rows = 0
        for row in r:
            if (row.get("dev_id") or "").upper() == "ADMIN":
                w.writerow(row); rows += 1
    if out.exists() and out.stat().st_size > 0:
        await m.answer_document(FSInputFile(out), caption="Export comisioane ADMIN")
    else:
        await m.answer("Nu am găsit linii de tip ADMIN în earnings_log.")

def list_requests_buttons(filter_func=None):
    items=[]
    for rid, inf in sorted(REQ_INDEX.items()):
        if filter_func and not filter_func(rid, inf): continue
        title = (inf.get("title") or "-")[:18]
        st = inf.get("status","nou")
        items.append((f"{rid} · {title} · {st}", rid))
    return items

# Assign (LEAD 100% implicit)
@rt.callback_query(F.data == "adm:assign")
async def adm_assign_pick_req(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_ids = list_requests_buttons(lambda rid,inf: (inf.get("status") or "nou")=="nou")
    if not req_ids: return await cq.answer("Nu există cereri noi.", show_alert=True)
    await cq.message.edit_text("🎯 Alege cererea pentru asignare:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=f"adm:assign:req:{rid}") ] for t,rid in req_ids]))

@rt.callback_query(F.data.startswith("adm:assign:req:"))
async def adm_assign_pick_dev(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_id = cq.data.split(":")[-1]
    info = REQ_INDEX.get(req_id); claimers = CLAIMS.get(req_id, {})
    if not info: return await cq.answer("REQ_ID necunoscut.", show_alert=True)
    if not claimers: return await cq.answer("Niciun dev nu a dat claim.", show_alert=True)
    buttons=[]
    for dev_id, meta in claimers.items():
        label = f"@{meta.get('username')}" if meta.get("username") else (meta.get("full_name") or str(dev_id))
        buttons.append((label, f"adm:assign:dev:{req_id}:{dev_id}"))
    await cq.message.edit_text(f"👨‍💻 Alege developerul (LEAD) pentru #{req_id}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t,c in buttons]))

@rt.callback_query(F.data.startswith("adm:assign:dev:"))
async def adm_assign_do(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    _,_,_,req_id, dev_id_txt = cq.data.split(":")
    try: dev_id = int(dev_id_txt)
    except: return await cq.answer("DEV_ID invalid.", show_alert=True)
    info = REQ_INDEX.get(req_id)
    if not info: return await cq.answer("REQ_ID necunoscut.", show_alert=True)

    meta = CLAIMS.get(req_id, {}).get(dev_id, {})
    dev_display = fmt_username_from_parts(meta.get("username",""), meta.get("full_name",""), dev_id)

    info["status"] = "in_lucru"
    info["assigned_dev_ids"].add(dev_id)
    info["roles"][dev_id] = {"role":"lead","pct":100}
    if not info.get("started_ts"): info["started_ts"] = now_iso()
    REQ_INDEX[req_id] = info
    update_order(req_id,
        assigned_dev_ids=",".join(str(x) for x in info["assigned_dev_ids"]),
        status="in_lucru", started_ts=info["started_ts"])

    # Preview către client
    try:
        lead_text = f"👨‍💻 Lead dev: {dev_display}\nETA: {info.get('deadline_iso') or info.get('deadline')}"
        await bot.send_message(info["user_id"], f"✅ Proiectul tău #{req_id} a intrat în lucru.\n{lead_text}", parse_mode="HTML")
    except: pass

    # Mesaj în topic
    try:
        topic_id = info.get("topic_id") or 0
        text_group = f"🆔 {req_id}: asignat LEAD către {dev_display} (status: in_lucru)."
        kb = InlineKeyboardBuilder()
        if info.get("topic_link"):
            kb.button(text="💬 Deschide discuția", url=info["topic_link"])
        kb.button(text="📊 Status",   callback_data=f"dev:status:req:{req_id}")
        kb.button(text="🗒️ Comment", callback_data=f"dev:comment:req:{req_id}")
        kb.button(text="⏫ 25%", callback_data=f"dev:progress:{req_id}:25")
        kb.button(text="⏫ 50%", callback_data=f"dev:progress:{req_id}:50")
        kb.button(text="⏫ 75%", callback_data=f"dev:progress:{req_id}:75")
        kb.adjust(2)
        await bot.send_message(DEV_GROUP_ID, text_group, parse_mode="HTML", message_thread_id=topic_id or None, reply_markup=kb.as_markup())
    except Exception as e:
        print("[W] assign->group:", e)

    await cq.message.edit_text(f"✅ Asignat LEAD: {req_id} → {dev_display}")
    await cq.answer()

# Add co-dev (procent)
@rt.callback_query(F.data == "adm:adddev")
async def adm_adddev_pick_req(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    reqs = list_requests_buttons(lambda rid,inf: (inf.get("status") or "nou") in {"nou","in_lucru"})
    if not reqs: return await cq.answer("Niciun proiect potrivit.", show_alert=True)
    await cq.message.edit_text("➕ Alege cererea:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=f"adm:adddev:req:{rid}") ] for t,rid in reqs]))

@rt.callback_query(F.data.startswith("adm:adddev:req:"))
async def adm_adddev_pick_dev(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_id = cq.data.split(":")[-1]
    claimers = CLAIMS.get(req_id, {})
    if not claimers: return await cq.answer("Nimeni nu a dat claim.", show_alert=True)
    buttons=[]
    for dev_id, meta in claimers.items():
        label = f"@{meta.get('username')}" if meta.get("username") else (meta.get("full_name") or str(dev_id))
        buttons.append((label, f"adm:adddev:add:{req_id}:{dev_id}"))
    await cq.message.edit_text(f"👥 Alege co‑dev pentru #{req_id}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t,c in buttons]))

@rt.callback_query(F.data.startswith("adm:adddev:add:"))
async def adm_adddev_do(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    _,_,_,req_id, dev_id_txt = cq.data.split(":")
    info = REQ_INDEX.get(req_id)
    if not info: return await cq.answer("REQ_ID necunoscut.", show_alert=True)
    try: dev_id = int(dev_id_txt)
    except: return await cq.answer("DEV_ID invalid.", show_alert=True)
    await state.update_data(adddev_req=req_id, adddev_id=dev_id)
    await state.set_state(AskPercent.waiting_pct)
    await cq.message.edit_text(f"Introduce procentul pentru co‑dev (0‑100) pentru #{req_id}:")
    await cq.answer()

@rt.message(AskPercent.waiting_pct)
async def set_helper_percent(m: Message, state: FSMContext):
    data = await state.get_data()
    req_id = data.get("adddev_req"); dev_id = int(data.get("adddev_id"))
    try:
        pct = int((m.text or "").strip())
        if pct < 0 or pct > 100: raise ValueError
    except:
        return await m.answer("Procent invalid. Trimite un număr între 0 și 100.")
    info = REQ_INDEX.get(req_id)
    if not info: await state.clear(); return await m.answer("REQ_ID necunoscut.")
    info["assigned_dev_ids"].add(dev_id)
    # ajustează totalul (max 100%)
    total_other = sum(v["pct"] for k,v in info["roles"].items())
    left = max(0, 100 - total_other)
    pct = min(pct, left if left>0 else pct)
    info["roles"][dev_id] = {"role":"helper","pct":pct}
    REQ_INDEX[req_id]=info
    update_order(req_id, assigned_dev_ids=",".join(str(x) for x in info["assigned_dev_ids"]))
    await state.clear()

    meta = CLAIMS.get(req_id, {}).get(dev_id, {})
    dev_display = fmt_username_from_parts(meta.get("username",""), meta.get("full_name",""), dev_id)
    try:
        topic_id = info.get("topic_id") or None
        await bot.send_message(DEV_GROUP_ID, f"➕ Co‑dev {dev_display} adăugat la #{req_id} ({pct}%).", parse_mode="HTML", message_thread_id=topic_id)
    except: pass
    await m.answer(f"✅ Co‑dev setat: {dev_display} ({pct}%) pentru #{req_id}.")

# Roluri
@rt.callback_query(F.data == "adm:role")
async def adm_role_pick_req(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    reqs = list_requests_buttons(lambda rid,inf: len(inf.get("assigned_dev_ids") or [])>0)
    if not reqs: return await cq.answer("Nicio cerere asignată.", show_alert=True)
    await cq.message.edit_text("👥 Alege cererea:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=f"adm:role:req:{rid}") ] for t,rid in reqs]))

@rt.callback_query(F.data.startswith("adm:role:req:"))
async def adm_role_show(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_id = cq.data.split(":")[-1]
    info = REQ_INDEX.get(req_id)
    if not info: return await cq.answer("REQ_ID necunoscut.", show_alert=True)
    lines=[f"👥 Roluri #{req_id}:"]
    for dev_id, meta in info["roles"].items():
        uname = CLAIMS.get(req_id, {}).get(dev_id, {}).get("username","")
        label = f"@{uname}" if uname else f"id {dev_id}"
        lines.append(f"• {label}: {meta['role']} ({meta['pct']}%)")
    await cq.message.edit_text("\n".join(lines))
    await cq.answer()

# Status & payout
@rt.callback_query(F.data == "adm:status")
async def adm_status_pick_req(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_ids = list_requests_buttons()
    if not req_ids: return await cq.answer("Nu există cereri.", show_alert=True)
    await cq.message.edit_text("📊 Alege cererea:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=f"adm:status:req:{rid}") ] for t,rid in req_ids]))

@rt.callback_query(F.data.startswith("adm:status:req:"))
async def adm_status_pick_state(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_id = cq.data.split(":")[-1]
    if req_id not in REQ_INDEX: return await cq.answer("REQ_ID necunoscut.", show_alert=True)
    st_buttons=[("nou",f"adm:status:set:{req_id}:nou"),("in_lucru",f"adm:status:set:{req_id}:in_lucru"),
                ("finalizat",f"adm:status:set:{req_id}:finalizat"),("anulat",f"adm:status:set:{req_id}:anulat")]
    await cq.message.edit_text(f"Status pentru #{req_id}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t,c in st_buttons]))

@rt.callback_query(F.data.startswith("adm:status:set:"))
async def adm_status_set(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    _,_,_,req_id,new_status = cq.data.split(":")
    info = REQ_INDEX.get(req_id)
    if not info: return await cq.answer("REQ_ID necunoscut.", show_alert=True)
    info["status"]=new_status; REQ_INDEX[req_id]=info
    update_order(req_id, status=new_status)

    # notifică devii
    for did in (info.get("assigned_dev_ids") or []):
        try: await bot.send_message(did, f"ℹ️ Proiect #{req_id}: status → {new_status}")
        except: pass

    if new_status == "finalizat":
        if not can_payout(cq.from_user.id):
            await cq.message.edit_text(f"Status setat la finalizat. Așteaptă confirmarea OWNER.")
            return await cq.answer()
        currency = (parse_amount_currency(info.get("budget_raw") or "")[1]) or "EUR"
        PAYOUT_CTX[cq.from_user.id] = {"req_id": req_id, "idx": 0, "devs": [], "amounts": {}, "currency": currency}
        devs=[]
        amt_total = parse_amount_currency(info.get("budget_raw") or "")[0] or 0
        for did, meta in info.get("roles", {}).items():
            auto = round(amt_total * meta.get("pct",0)/100, 2)
            uname = CLAIMS.get(req_id, {}).get(did, {}).get("username","")
            devs.append((did, uname, auto))
        PAYOUT_CTX[cq.from_user.id]["devs"]=devs
        if devs:
            did, un, auto = devs[0]
            label = f"@{un}" if un else f"id {did}"
            await cq.message.edit_text(f"💵 Payout pentru #{req_id}\nSumă pt {label} (sugestie {auto} {currency}):")
            await state.set_state(AdminPayout.picking)
        return await cq.answer("Payout wizard pornit.")
    else:
        try:
            topic_id = info.get("topic_id") or None
            await bot.send_message(DEV_GROUP_ID, f"🆔 {req_id}: status → <b>{new_status}</b>.", parse_mode="HTML", message_thread_id=topic_id)
        except: pass
        await cq.message.edit_text(f"✅ Status pentru {req_id} → {new_status}")
        return await cq.answer()

@rt.message(AdminPayout.picking)
async def admin_payout_collect(m: Message, state: FSMContext):
    ctx = PAYOUT_CTX.get(m.from_user.id)
    if not ctx:
        await state.clear(); return await m.answer("Context payout pierdut.")
    req_id = ctx["req_id"]; devs = ctx["devs"]; idx = ctx["idx"]
    try:
        amount = float((m.text or "0").replace(",", "."))
        if amount < 0: raise ValueError
    except:
        return await m.answer("Sumă invalidă. Exemplu: 150 sau 150.50")

    did, uname, _auto = devs[idx]
    ctx["amounts"][did] = amount

    if idx + 1 < len(devs):
        ctx["idx"] += 1
        ndid, nun, nauto = devs[idx+1]
        label = f"@{nun}" if nun else f"id {ndid}"
        await m.answer(f"Suma pentru {label} (sugestie {nauto} {ctx['currency']}):")
    else:
        for did2, amt in ctx["amounts"].items():
            uname2 = CLAIMS.get(req_id, {}).get(did2, {}).get("username","")
            append_earning(req_id, str(did2), uname2, amt, ctx["currency"], "admin confirm")
        total_dev = sum(ctx["amounts"].values())
        comm = round(total_dev * (ADMIN_COMMISSION_PCT/100.0), 2)
        if comm > 0:
            append_earning(req_id, "ADMIN", "admin", comm, ctx["currency"], f"commission {ADMIN_COMMISSION_PCT}%")
        update_order(req_id, status="finalizat_confirmat")
        REQ_INDEX[req_id]["status"] = "finalizat_confirmat"
        await m.answer(f"✅ Plăți confirmate pentru #{req_id}. (comision {comm} {ctx['currency']})")
        try:
            topic = REQ_INDEX[req_id].get("topic_id") or None
            await bot.send_message(DEV_GROUP_ID, f"🏁 {req_id}: proiect finalizat și plățile confirmate.", message_thread_id=topic)
        except: pass
        PAYOUT_CTX.pop(m.from_user.id, None)
        await state.clear()

# ==================== Detalii / Active ====================
@rt.callback_query(F.data == "adm:details")
async def adm_details_pick_req(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_ids = list(REQ_INDEX.keys())
    if not req_ids: return await cq.answer("Nu există cereri.", show_alert=True)
    await cq.message.edit_text("🧾 Alege cererea:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=rid, callback_data=f"adm:details:req:{rid}") ] for rid in sorted(req_ids)]))

@rt.callback_query(F.data.startswith("adm:details:req:"))
async def adm_details_show(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_id = cq.data.split(":")[-1]
    info = REQ_INDEX.get(req_id) or get_order(req_id)
    if not info: return await cq.answer("REQ_ID necunoscut.", show_alert=True)
    g = lambda k: info.get(k,"") if isinstance(info, dict) else ""
    devs_display = []
    roles = info.get("roles",{})
    for did, meta in roles.items():
        uname = CLAIMS.get(req_id, {}).get(did, {}).get("username","")
        devs_display.append(f"{'@'+uname if uname else 'id '+str(did)} {meta['role']}({meta['pct']}%)")
    resp = (
        f"🧾 <b>Detalii #{req_id}</b>\n"
        f"👤 Client: {g('full_name')} (@{g('username')}) id {g('user_id')}\n"
        f"📦 Categoria: {g('category')}\n"
        f"📝 Titlu: {g('title')}\n"
        f"💰 Buget: {g('budget_raw')}\n"
        f"⏳ Termen: {g('deadline')} ({g('deadline_iso') or 'n/a'})\n"
        f"🔧 Status: {g('status')}\n"
        f"👨‍💻 Dev(s): " + (", ".join(devs_display) or "-") + "\n"
        f"🔗 Topic: {g('topic_link') or 'n/a'}\n"
        f"🗒️ Notes: {g('notes')}\n"
        f"⏱ Start: {g('started_ts') or 'n/a'}"
    )
    await cq.message.edit_text(resp, parse_mode="HTML")
    await cq.answer()

@rt.callback_query(F.data == "adm:active")
async def adm_active(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    actives=[(rid, inf) for rid,inf in REQ_INDEX.items() if (inf.get("status") or "nou") in {"nou","in_lucru"}]
    if not actives:
        await cq.message.edit_text("Nu sunt proiecte active.")
        return await cq.answer()
    lines=["📋 Proiecte active:"]
    for rid, inf in actives[:50]:
        started = inf.get("started_ts","")
        elapsed = human_delta(started)
        left = time_left(inf.get("deadline_iso",""))
        devs = []
        for did, meta in (inf.get("roles") or {}).items():
            u = CLAIMS.get(rid, {}).get(did, {}).get("username","")
            devs.append(f"{'@'+u if u else did}:{meta['pct']}%")
        title = (inf.get("title") or "-")[:22]
        lines.append(f"#{rid} · {title} · devs[{', '.join(devs) or '-'}] · ⏱ {elapsed} · ⌛ {left}")
    await cq.message.edit_text("\n".join(lines))
    await cq.answer()

# ==================== Comentarii ====================
@rt.callback_query(F.data == "adm:comment")
async def adm_comment_pick_req(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_ids = list(REQ_INDEX.keys())
    if not req_ids: return await cq.answer("Nu există cereri.", show_alert=True)
    await cq.message.edit_text("💬 Alege cererea:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=rid, callback_data=f"adm:comment:req:{rid}") ] for rid in sorted(req_ids)]))

@rt.callback_query(F.data.startswith("adm:comment:req:"))
async def adm_comment_wait_note(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    req_id = cq.data.split(":")[-1]
    await state.update_data(comment_req_id=req_id)
    await state.set_state(DevComment.waiting_note)
    await cq.message.edit_text(f"Scrie comentariul pentru #{req_id} (trimite mesaj).")
    await cq.answer()

@rt.message(DevComment.waiting_note)
async def comment_save(m: Message, state: FSMContext):
    data = await state.get_data(); req_id = data.get("comment_req_id")
    note_txt = (m.text or "").strip()
    if not req_id:
        await state.clear(); return await m.answer("Context pierdut.")
    prev = (REQ_INDEX.get(req_id, {}).get("notes") or "").strip()
    author = "admin" if is_admin(m.from_user.id) else fmt_username_from_parts(m.from_user.username or "", m.from_user.full_name or "", m.from_user.id)
    new_line = f"[{now_iso()}] ({author}) {note_txt}"
    combined = (prev + "\n" + new_line).strip() if prev else new_line
    if req_id in REQ_INDEX: REQ_INDEX[req_id]["notes"] = combined
    update_order(req_id, notes=combined)
    await state.clear(); await m.answer(f"🗒️ Comentariu salvat pentru #{req_id}.")
    for did in (REQ_INDEX[req_id].get("assigned_dev_ids") or []):
        try: await bot.send_message(did, f"💬 Comentariu nou la #{req_id}: {note_txt[:150]}")
        except: pass
    try:
        topic_id = REQ_INDEX[req_id].get("topic_id") or None
        await bot.send_message(DEV_GROUP_ID, f"💬 Comentariu la #{req_id}: {note_txt}", message_thread_id=topic_id)
    except: pass

# ==================== Controale DEV ====================
def ensure_assigned_dev(req_id: str, user_id: int) -> bool:
    info = REQ_INDEX.get(req_id)
    if not info: return False
    ids = info.get("assigned_dev_ids") or set()
    return str(user_id) in {str(x) for x in ids}

@rt.callback_query(F.data.startswith("dev:status:req:"))
async def dev_status_pick(cq: CallbackQuery):
    req_id = cq.data.split(":")[-1]
    if not ensure_assigned_dev(req_id, cq.from_user.id):
        return await cq.answer("Nu ești asignat.", show_alert=True)
    st_buttons=[("nou",f"dev:status:set:{req_id}:nou"),("in_lucru",f"dev:status:set:{req_id}:in_lucru"),
                ("finalizat",f"dev:status:set:{req_id}:finalizat"),("anulat",f"dev:status:set:{req_id}:anulat")]
    await cq.message.reply(f"Schimbă status pentru #{req_id}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t,c in st_buttons]))
    await cq.answer()

@rt.callback_query(F.data.startswith("dev:status:set:"))
async def dev_status_set(cq: CallbackQuery):
    _,_,_,req_id,new_status = cq.data.split(":")
    if not ensure_assigned_dev(req_id, cq.from_user.id):
        return await cq.answer("Nu ești asignat.", show_alert=True)
    REQ_INDEX[req_id]["status"]=new_status; update_order(req_id, status=new_status)
    await cq.message.reply(f"✅ (dev) Status pentru {req_id} → {new_status}")
    try:
        topic_id = REQ_INDEX[req_id].get("topic_id") or None
        await bot.send_message(DEV_GROUP_ID, f"🆔 {req_id}: status de dev → <b>{new_status}</b>.", parse_mode="HTML", message_thread_id=topic_id)
    except: pass
    await cq.answer("OK")

@rt.callback_query(F.data.startswith("dev:comment:req:"))
async def dev_comment_start(cq: CallbackQuery, state: FSMContext):
    req_id = cq.data.split(":")[-1]
    if not ensure_assigned_dev(req_id, cq.from_user.id):
        return await cq.answer("Nu ești asignat.", show_alert=True)
    await state.update_data(comment_req_id=req_id)
    await state.set_state(DevComment.waiting_note)
    await cq.message.reply(f"Trimite comentariul tău pentru #{req_id}.")
    await cq.answer()

@rt.callback_query(F.data.startswith("dev:progress:"))
async def dev_progress(cq: CallbackQuery):
    _,_,req_id,p = cq.data.split(":")
    if not ensure_assigned_dev(req_id, cq.from_user.id):
        return await cq.answer("Nu ești asignat.", show_alert=True)
    p = int(p)
    note = f"Progres raportat: {p}%"
    prev = (REQ_INDEX.get(req_id, {}).get("notes") or "").strip()
    new_line = f"[{now_iso()}] (dev {fmt_username_from_parts(cq.from_user.username or '', cq.from_user.full_name or '', cq.from_user.id)}) {note}"
    combined = (prev + "\n" + new_line).strip() if prev else new_line
    REQ_INDEX[req_id]["notes"] = combined; update_order(req_id, notes=combined)
    try:
        topic = REQ_INDEX[req_id].get("topic_id") or None
        await bot.send_message(DEV_GROUP_ID, f"📈 #{req_id}: {note}", message_thread_id=topic)
    except: pass
    await cq.answer("Progres salvat.")

# /my: dashboard dev
@rt.message(Command("my"))
async def my_dashboard(m: Message):
    uid = m.from_user.id
    active=[]; finished=[]
    for rid, inf in REQ_INDEX.items():
        if str(uid) not in {str(x) for x in (inf.get("assigned_dev_ids") or set())}: continue
        st = inf.get("status","nou")
        (active if st in {"nou","in_lucru"} else finished).append((rid, inf))
    total_money, cur, finished_count = dev_totals(uid)

    lines = ["👨‍💻 Dashboard", f"• Active: {len(active)}",
             f"• Finalizate confirmate: {finished_count}",
             f"• Total confirmat: {total_money:.2f} {cur}", ""]
    if active:
        for rid, inf in active[:10]:
            elapsed = human_delta(inf.get("started_ts",""))
            left = time_left(inf.get("deadline_iso",""))
            title = (inf.get("title") or "-")[:24]
            lines.append(f"#{rid} · {title} · ⏱ {elapsed} · ⌛ {left}")
    else:
        lines.append("Niciun proiect activ.")
    await m.answer("\n".join(lines))

    for rid, inf in active[:5]:
        kb = InlineKeyboardBuilder()
        if inf.get("topic_link"):
            kb.button(text="💬 Deschide topic", url=inf["topic_link"])
        kb.button(text="⏫ 25%", callback_data=f"dev:progress:{rid}:25")
        kb.button(text="⏫ 50%", callback_data=f"dev:progress:{rid}:50")
        kb.button(text="⏫ 75%", callback_data=f"dev:progress:{rid}:75")
        kb.adjust(2)
        await m.answer(f"Controale #{rid}", reply_markup=kb.as_markup())

# ==================== Export lunar ====================
@rt.callback_query(F.data == "adm:export")
async def adm_export_prompt(cq: CallbackQuery):
    if not is_admin(cq.from_user.id): return await cq.answer("Doar admin/manager.", show_alert=True)
    await cq.message.edit_text("Trimite comanda: /export_month YYYY-MM")

@rt.message(Command("export_month"))
async def export_month(m: Message):
    if not is_admin(m.from_user.id): return
    try:
        ym = (m.text or "").split(" ",1)[1].strip()
        year, month = [int(x) for x in ym.split("-")]
    except:
        return await m.answer("Format: /export_month YYYY-MM")
    start = datetime.date(year, month, 1)
    end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    rows = [r for r in load_log() if r.get("ts","") and start.isoformat() <= r["ts"][:10] < end.isoformat()]
    out = pathlib.Path(f"export_{ym}.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES); w.writeheader()
        for r in rows: w.writerow(r)
    await m.answer_document(FSInputFile(out), caption=f"Export {ym}")

# ==================== Weekly summary ====================
async def weekly_summaries():
    sent_for = set()
    while True:
        now = datetime.datetime.now()
        if now.weekday()==0 and now.hour==9 and (now.minute<2):  # Luni 09:00
            key = now.strftime("%Y-%m-%d")
            if key not in sent_for:
                dev_ids=set()
                for _, inf in REQ_INDEX.items():
                    for did in (inf.get("assigned_dev_ids") or []): dev_ids.add(did)
                for did in dev_ids:
                    active=[(rid,inf) for rid,inf in REQ_INDEX.items() if str(did) in {str(x) for x in (inf.get("assigned_dev_ids") or set())} and (inf.get("status") or "nou") in {"nou","in_lucru"}]
                    total, cur, fin = dev_totals(did)
                    lines = [f"📬 Rezumat săptămânal", f"• Active: {len(active)}", f"• Finalizate confirmate: {fin}", f"• Total confirmat: {total:.2f} {cur}"]
                    try: await bot.send_message(did, "\n".join(lines))
                    except: pass
                sent_for.add(key)
        await asyncio.sleep(60)

# ==================== Utilitare ====================
@rt.message(Command("catalog"))
async def cmd_catalog(m: Message):
    L = LANGS[get_lang(m.from_user.id)]
    await m.answer(L["menu_title"], reply_markup=main_menu_kb(m.from_user.id))

@rt.message(Command("terms"))
async def cmd_terms(m: Message):
    await m.answer("📜 Termeni: servicii personalizate, fără jocuri de noroc cu bani reali. Pentru casino-bot folosim puncte virtuale.")

@rt.message(Command("whoami"))
async def whoami(m: Message):
    await m.answer(f"id: {m.from_user.id}\nusername: @{m.from_user.username}")

# ==================== Run ====================
dp.include_router(rt)

async def main():
    print("Bot – multi-dev, topics, payouts, export, notificări + categorii & idei.")
    asyncio.create_task(weekly_summaries())
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
