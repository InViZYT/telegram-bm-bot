import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
BM_TOKEN = os.getenv("BM_TOKEN")

if not TG_TOKEN or not BM_TOKEN:
    print("ВНИМАНИЕ: Токены не найдены! Проверьте наличие и заполнение файла .env")

bot = telebot.TeleBot(TG_TOKEN)
HEADERS = {"Authorization": f"Bearer {BM_TOKEN}"}

# === ПУТЬ К БАЗЕ ДАННЫХ ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tracker.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked_players (
            chat_id INTEGER,
            bm_id TEXT,
            player_name TEXT,
            PRIMARY KEY (chat_id, bm_id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ФОРМАТИРОВАНИЯ ДАТЫ ===
def format_iso_date(iso_str):
    if not iso_str:
        return "Неизвестно"
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime('%d.%m.%Y %H:%M (UTC)')
    except:
        return "Не удалось прочесть дату"

# === УМНАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ИСТОРИИ И АКТИВНОСТИ ===
def get_player_status(bm_id):
    try:
        player_url = f"https://api.battlemetrics.com/players/{bm_id}"
        resp_player = requests.get(player_url, headers=HEADERS).json()
        
        attributes = resp_player.get('data', {}).get('attributes', {})
        last_seen_raw = attributes.get('lastSeen')
        last_seen_formatted = format_iso_date(last_seen_raw)
        player_name = attributes.get('name', 'Игрок')
        
        hist_url = f"https://api.battlemetrics.com/players/{bm_id}/servers?page[size]=1&include=server"
        hist_resp = requests.get(hist_url, headers=HEADERS)
        
        if hist_resp.status_code == 429:
            return player_name, "Лимит API", "", "", 0, last_seen_formatted
            
        h_data = hist_resp.json()
        
        if 'included' in h_data:
            for item in h_data['included']:
                if item.get('type') == 'server':
                    attrs = item['attributes']
                    return player_name, attrs.get('name', 'Неизвестно'), attrs.get('ip', ''), attrs.get('port', ''), 0, last_seen_formatted
                    
        if 'data' in h_data and len(h_data['data']) > 0:
            first = h_data['data'][0]
            if first.get('type') == 'server':
                attrs = first.get('attributes', {})
                return player_name, attrs.get('name', 'Скрыт профиль'), attrs.get('ip', ''), attrs.get('port', ''), 0, last_seen_formatted
                
        return player_name, "Скрыт профиль в истории", "", "", 0, last_seen_formatted
        
    except Exception as e:
        return "Игрок", f"Ошибка парсинга: {e}", "", "", 0, "Не определено"

def get_track_markup(chat_id, bm_id, player_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM tracked_players WHERE chat_id = ? AND bm_id = ?", (chat_id, bm_id))
    is_tracked = cursor.fetchone()
    conn.close()
    
    markup = InlineKeyboardMarkup()
    if is_tracked:
        markup.add(InlineKeyboardButton(text="❌ Удалить из отслеживания", callback_data=f"untrack_{bm_id}_{player_name[:15]}"))
    else:
        markup.add(InlineKeyboardButton(text="⭐ Добавить в отслеживание", callback_data=f"track_{bm_id}_{player_name[:15]}"))
    return markup

def get_main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🔍 Найти игрока"), KeyboardButton("📜 Мой список отслеживания"))
    return markup

@bot.message_handler(commands=['start'])
def start_welcome(message):
    bot.send_message(message.chat.id, "Привет! Используй меню внизу для управления.", reply_markup=get_main_menu())

@bot.message_handler(commands=['findid'])
def search_by_id(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Использование: `/findid <ID_игрока_в_БМ>`\nПример: `/findid 1160958514`", parse_mode="Markdown")
        return
        
    bm_id = parts[1].strip()
    status_msg = bot.send_message(message.chat.id, f"⏳ Загружаю профиль BattleMetrics по ID: `{bm_id}`...", parse_mode="Markdown")
    
    player_name, full_server_name, ip, port, _, last_seen = get_player_status(bm_id)
    safe_player_name = player_name.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
    safe_server_name = full_server_name.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
    
    server_info = f"{safe_server_name}"
    if ip and port:
        server_info += f"\n🌐 IP: `{ip}:{port}`"
        
    profile_url = f"https://www.battlemetrics.com/players/{bm_id}"
    
    status_text = (
        f"👤 Игрок: **{safe_player_name}**\n"
        f"🔗 [Открыть профиль на BattleMetrics]({profile_url})\n\n"
        f"⏱ Последний заход: `{last_seen}`\n"
        f"🕵️ Последний сервер:\n{server_info}"
    )
    
    markup = get_track_markup(message.chat.id, bm_id, player_name)
    bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=status_text, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.message_handler(func=lambda msg: msg.text == "🔍 Найти игрока")
def search_button_click(message):
    msg = bot.send_message(message.chat.id, "Введите ник или Steam ID игрока:")
    bot.register_next_step_handler(msg, process_search)

def process_search(message):
    query = message.text.strip()
    if not query:
        return
        
    status_msg = bot.send_message(message.chat.id, "⏳ Ищу в базе BattleMetrics...")
    search_url = f"https://api.battlemetrics.com/players?filter[search]={query}&page[size]=5"
    
    try:
        resp = requests.get(search_url, headers=HEADERS)
        if resp.status_code == 429:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="Слишком много запросов. Подожди минуту.")
            return
            
        search_response = resp.json()
        
        if not search_response.get('data'):
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="Никого не найдено.")
            return
        
        markup = InlineKeyboardMarkup()
        
        for player in search_response['data']:
            bm_id = player['attributes']['id']
            name = player['attributes']['name']
            display_name = name[:10] + ".." if len(name) > 10 else name
            
            _, server_name, _, _, _, _ = get_player_status(bm_id)
            display_server = server_name[:14] + ".." if len(server_name) > 14 else server_name
            
            btn_text = f"🔴 {display_name} | Был: {display_server}"
                
            btn = InlineKeyboardButton(text=btn_text, callback_data=f"view_{bm_id}")
            markup.add(btn)
            
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"Топ-5 результатов по запросу *{query}* (Также доступен поиск по команде /findid ID):", reply_markup=markup, parse_mode="Markdown")
        
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"Ошибка поиска: {e}")

@bot.message_handler(func=lambda msg: msg.text == "📜 Мой список отслеживания")
def show_tracked_list(message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT bm_id, player_name FROM tracked_players WHERE chat_id = ?", (message.chat.id,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        bot.send_message(message.chat.id, "Ваш список пуст.")
        return
        
    markup = InlineKeyboardMarkup()
    for row in rows:
        btn = InlineKeyboardButton(text=f"👤 {row[1]}", callback_data=f"view_{row[0]}")
        markup.add(btn)
        
    bot.send_message(message.chat.id, "📋 Игроки в вашем списке:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    
    if call.data.startswith('view_'):
        bm_id = call.data.split('_')[1]
        bot.answer_callback_query(call.id, "Загружаю статус...")
        
        try:
            player_url = f"https://api.battlemetrics.com/players/{bm_id}"
            player_response = requests.get(player_url, headers=HEADERS).json()
            player_name = player_response.get('data', {}).get('attributes', {}).get('name', 'Игрок')
            
            safe_player_name = player_name.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
            
            _, full_server_name, ip, port, _, last_seen = get_player_status(bm_id)
            safe_server_name = full_server_name.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
            
            server_info = f"{safe_server_name}"
            if ip and port:
                server_info += f"\n🌐 IP: `{ip}:{port}`"
            
            profile_url = f"https://www.battlemetrics.com/players/{bm_id}"
                    
            status_text = (
                f"👤 Игрок: **{safe_player_name}**\n"
                f"🔗 [Открыть профиль на BattleMetrics]({profile_url})\n\n"
                f"⏱ Последний заход: `{last_seen}`\n"
                f"🕵️ Последний сервер:\n{server_info}"
            )
                
            markup = get_track_markup(chat_id, bm_id, player_name)
            
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=status_text, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
            
        except Exception as e:
            print(f"DEBUG CRITICAL ERROR: {e}")
            bot.send_message(chat_id, f"❌ Произошла ошибка при загрузке данных:\n`{e}`", parse_mode="Markdown")

    elif call.data.startswith('track_'):
        _, bm_id, player_name = call.data.split('_', 2)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("INSERT INTO tracked_players (chat_id, bm_id, player_name) VALUES (?, ?, ?)", (chat_id, bm_id, player_name))
            conn.commit()
            bot.answer_callback_query(call.id, "Игрок добавлен!", show_alert=True)
        except sqlite3.IntegrityError:
            bot.answer_callback_query(call.id, "Уже в списке!")
        finally:
            conn.close()
            bot.delete_message(chat_id, call.message.message_id)
        
    elif call.data.startswith('untrack_'):
        bm_id = call.data.split('_')[1]
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM tracked_players WHERE chat_id = ? AND bm_id = ?", (chat_id, bm_id))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "Удален из списка!", show_alert=True)
        bot.delete_message(chat_id, call.message.message_id)

if __name__ == "__main__":
    print("Бот запущен и полностью готов к работе!")
    bot.infinity_polling()