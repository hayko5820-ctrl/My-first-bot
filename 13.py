import logging
import sqlite3
import random
import string
import requests
import certifi
import fake_useragent
import glob
import re
import asyncio
from datetime import datetime, timedelta
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from g4f.client import Client
from telethon import TelegramClient, functions
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, 
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# Игнорируем предупреждения о незащищенных запросах
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Токен бота
TOKEN = '8500453556:AAGipXXl9Z5N7T0I6nubIKPvsWotOCgOvps'

# Список ID администраторов
ADMIN_IDS = [5905797853, 8648941987]

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Подключение к базе данных
conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    subscription_end DATETIME
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS user_actions (
    user_id INTEGER,
    action_time DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')
conn.commit()

# Состояния для ConversationHandler (Админка + Функции бота)
(
    ID, DURATION, CONFIRMATION, REMOVE_ID, REMOVE_CONFIRMATION, BROADCAST,
    ACTIVATE_PHONE, REPORT_NICK, REPORT_REASON_STATE, REPORT_LINK, UNBAN_PHONE
) = range(11)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ИЗ APP.PY ---
def generate_random_email():
    domains = ["gmail.com", "hotmail.com"]
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"{name}@{random.choice(domains)}"

def generate_random_phone_number():
    prefixes = ['+7', '+380']
    number = ''.join(random.choices(string.digits, k=10))
    return f"{random.choice(prefixes)}{number}"

def generate_user_agent():
    return fake_useragent.UserAgent().random


# --- ОСНОВНЫЕ КОМАНДЫ И МЕНЮ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    cursor.execute('INSERT INTO user_actions (user_id) VALUES (?)', (user_id,))
    conn.commit()

    # Проверка подписки на канал
    try:
        user_status = await context.bot.get_chat_member(chat_id='@andreypidorloxr', user_id=user_id)
        if user_status.status not in ['member', 'administrator', 'creator']:
            await update.message.reply_text('❌ Пожалуйста, подпишитесь на канал @andreypidorloxr, чтобы пользоваться ботом.')
            return
    except Exception as e:
        await update.message.reply_text(f'⚠️ Ошибка при проверке подписки: {e}')
        return

    # Проверка наличия активной подписки
    cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result:
        subscription_end = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        if subscription_end > datetime.now():
            # Активная подписка -> показываем полный функционал бота
            keyboard = [
                [InlineKeyboardButton("⚡️ Активация (Спам сессий)", callback_data='menu_activate')],
                [InlineKeyboardButton("🤖 Жалоба на юзера/пост (ИИ)", callback_data='menu_report')],
                [InlineKeyboardButton("🔓 Запрос на разбан", callback_data='menu_unban')],
                [InlineKeyboardButton("🆘 Поддержка", callback_data='support'), InlineKeyboardButton("💰 Прайс", callback_data='price')],
                [InlineKeyboardButton("🛒 Купить подписку", callback_data='buy_subscription')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text('👋 Добро пожаловать! Выберите нужную функцию:', reply_markup=reply_markup)
        else:
            await send_expired_menu(update)
    else:
        await send_expired_menu(update)

async def send_expired_menu(update: Update):
    keyboard = [
        [InlineKeyboardButton("💰 Прайс", callback_data='price')],
        [InlineKeyboardButton("🛒 Купить подписку", callback_data='buy_subscription')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = '❌ У вас нет активной подписки или она истекла. Приобретите подписку:'
    if update.callback_query:
        await update.callback_query.edit_message_text(text=msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=msg, reply_markup=reply_markup)

async def check_sub_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        return True
    cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result and datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S') > datetime.now():
        return True
    return False


# --- ОБРАБОТЧИКИ КНОПОК И ФУНКЦИЙ ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == 'support':
        await query.edit_message_text(text="🆘 Свяжитесь с поддержкой: @TYNDROV")
    elif query.data == 'price':
        await query.edit_message_text(text="💰 Цены на подписку:\n1 день - $2.8\n1 неделя - $7.3\n1 месяц - $13.5\n1 год - $35\nНавсегда - $50")
    elif query.data == 'buy_subscription':
        await query.edit_message_text(text="🛒 Для покупки подписки свяжитесь с @hanori67")


# 1. АКТИВАЦИЯ (Запросы на телефон)
async def start_activate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_sub_middleware(update, context):
        await update.callback_query.message.reply_text("❌ У вас нет активной подписки!")
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_menu')]]
    await update.callback_query.edit_message_text(
        text="📱 Введите номер телефона для отправки запросов (например, +79991234567):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ACTIVATE_PHONE

async def process_activate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    await update.message.reply_text("⏳ Запускаю отправку запросов, подождите...")
    
    user = fake_useragent.UserAgent().random
    headers = {'user-agent': user}
    
    try:
        requests.post('https://oauth.telegram.org/auth/request?bot_id=1852523856&origin=https%3A%2F%2Fcabinet.presscode.app&embed=1&return_to=https%3A%2F%2Fcabinet.presscode.app%2Flogin', headers=headers, data={'phone': phone}, timeout=5)
        requests.post('https://translations.telegram.org/auth/request', headers=headers, data={'phone': phone}, timeout=5)
        requests.post('https://oauth.telegram.org/auth/request?bot_id=1093384146&origin=https%3A%2F%2Foff-bot.ru&embed=1&request_access=write&return_to=https%3A%2F%2Foff-bot.ru%2Fregister%2Fconnected-accounts%2Fsmodders_telegram%2F%3Fsetup%3D1', headers=headers, data={'phone': phone}, timeout=5)
        requests.post('https://oauth.telegram.org/auth/request?bot_id=466141824&origin=https%3A%2F%2Fmipped.com&embed=1&request_access=write&return_to=https%3A%2F%2Fmipped.com%2Ff%2Fregister%2Fconnected-accounts%2Fsmodders_telegram%2F%3Fsetup%3D1', headers=headers, data={'phone': phone}, timeout=5)
        requests.post('https://my.telegram.org/auth/send_password', headers=headers, data={'phone': phone}, timeout=5)
        
        await update.message.reply_text("✅ Запросы успешно отправлены на номер: " + phone)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при отправке запросов: {e}")
        
    return ConversationHandler.END


# 2. ЖАЛОБА С ИИ И TELETHON
async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_sub_middleware(update, context):
        await update.callback_query.message.reply_text("❌ У вас нет активной подписки!")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_menu')]]
    await update.callback_query.edit_message_text(
        text="📝 Введите никнейм нарушителя (например, @username):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REPORT_NICK

async def report_nick_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['report_nickname'] = update.message.text
    await update.message.reply_text("⚠️ Укажите тип нарушения (например: Спам, Мошенничество, Порнография):")
    return REPORT_REASON_STATE

async def report_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['report_reason'] = update.message.text
    await update.message.reply_text("🔗 Теперь отправьте ссылку на сообщение/пост в Telegram (например, https://t.me/channel/123):")
    return REPORT_LINK

async def report_finish_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link = update.message.text.strip()
    nickname = context.user_data.get('report_nickname', '@user')
    reason = context.user_data.get('report_reason', 'SPAM')

    await update.message.reply_text("🤖 Генерирую жалобу через ИИ и отправляю репорты с сессий...")

    try:
        # Генерация текста через g4f
        client = Client()
        prompt = f"Дополни и улучши текст: Здравствуйте техническая поддержка телеграмма! Я наткнулся на пользователя с никнеймом: {nickname} он нарушает правило в Telegram: {reason}. Пожалуйста, примите меры и заблокируйте его аккаунт, спасибо."
        ai_resp = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
        message_text = ai_resp.choices[0].message.content

        # Отправка жалоб на support.telegram.org
        for _ in range(10): # Снижено до 10 для скорости бота
            requests.post("https://telegram.org/support?setln=ru", data={
                "subject": "Жалоба на пользователя",
                "message": message_text,
                "email": generate_random_email(),
                "phone": generate_random_phone_number()
            }, headers={"User-Agent": generate_user_agent()}, verify=certifi.where(), timeout=5)

        # Отправка репортов через Telethon (если есть сессии)
        api_id = '24641445'
        api_hash = 'cbd16f1ca6464bf64338e45abd85ccdf'
        session_files = glob.glob('SESSION/*.session')
        
        telethon_count = 0
        if session_files:
            match = re.match(r'https://t.me/([^/]+)/(\d+)', link)
            if match:
                chat_username = match.group(1)
                for session_file in session_files:
                    try:
                        async with TelegramClient(session_file, api_id, api_hash, device_model='Android') as client_t:
                            chat = await client_t.get_entity(chat_username)
                            await client_t(functions.messages.ReportSpamRequest(peer=chat))
                            telethon_count += 1
                    except Exception:
                        pass

        await update.message.reply_text(f"✅ Жалоба успешно отправлена!\n🤖 Текст сгенерирован ИИ\n📱 Telethon сессий отработало: {telethon_count}")
    except Exception as e:
        await update.message.reply_text(f"❌ Произошла ошибка при отправке жалобы: {e}")

    return ConversationHandler.END


# 3. РАЗБАН
async def start_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_sub_middleware(update, context):
        await update.callback_query.message.reply_text("❌ У вас нет активной подписки!")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_menu')]]
    await update.callback_query.edit_message_text(
        text="🔓 Введите ваш заблокированный номер телефона (например, +79991234567):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return UNBAN_PHONE

async def process_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    await update.message.reply_text("⏳ Отправляем запросы на разблокировку...")

    complaint_text = f"Здравствуйте Telegram поддержка! Мой номер телефона {phone} был заблокирован. Я не нарушал правила ToS. Пожалуйста, разблокируйте мой аккаунт."

    try:
        for _ in range(15):
            requests.post("https://telegram.org/support?setln=ru", data={
                "subject": "Жалоба на пользователя",
                "message": complaint_text,
                "email": generate_random_email(),
                "phone": phone
            }, headers={"User-Agent": generate_user_agent()}, verify=certifi.where(), timeout=5)

        await update.message.reply_text("✅ Запросы на разбан успешно отправлены.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

    return ConversationHandler.END


# --- АДМИН-ПАНЕЛЬ ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text('❌ У вас нет доступа к этой команде.')
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("✅ Выдать подписку", callback_data='grant_subscription')],
        [InlineKeyboardButton("❌ Снять подписку", callback_data='revoke_subscription')],
        [InlineKeyboardButton("📋 Список пользователей", callback_data='list_users')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='broadcast')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('👨‍💻 Админ панель:', reply_markup=reply_markup)
    return ID

async def grant_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_admin')]]
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text="📝 Введите ID пользователя для выдачи подписки:", reply_markup=InlineKeyboardMarkup(keyboard))
    return DURATION

async def duration_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = int(update.message.text)
        context.user_data['grant_user_id'] = user_id
        await update.message.reply_text('⏳ Введите длительность подписки (например, 1d, 1m, 1y):')
        return CONFIRMATION
    except ValueError:
        await update.message.reply_text('❌ Введите корректный ID (только цифры)')
        return DURATION

async def confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    duration = update.message.text
    user_id = context.user_data['grant_user_id']
    now = datetime.now()

    if duration.endswith('d'):
        subscription_end = now + timedelta(days=int(duration[:-1]))
    elif duration.endswith('m'):
        subscription_end = now + timedelta(days=30*int(duration[:-1]))
    elif duration.endswith('y'):
        subscription_end = now + timedelta(days=365*int(duration[:-1]))
    else:
        await update.message.reply_text('❌ Неверный формат. Попробуйте снова (например, 30d):')
        return DURATION

    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, subscription_end) VALUES (?, ?, ?)',
                  (user_id, None, subscription_end.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()

    try:
        await context.bot.send_message(chat_id=user_id, text=f'✅ Вам выдана подписка до {subscription_end.strftime("%Y-%m-%d %H:%M:%S")}! Используйте /start')
    except Exception:
        pass

    await update.message.reply_text(f'✅ Подписка успешно выдана пользователю {user_id}!')
    return ConversationHandler.END

async def revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_admin')]]
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text="📝 Введите ID пользователя для снятия подписки:", reply_markup=InlineKeyboardMarkup(keyboard))
    return REMOVE_CONFIRMATION

async def remove_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = int(update.message.text)
        cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()
        await update.message.reply_text(f'✅ Подписка снята у пользователя {user_id}.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('❌ Введите корректный ID пользователя.')
        return REMOVE_CONFIRMATION

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    cursor.execute('SELECT user_id, subscription_end FROM users')
    subscribed_users = cursor.fetchall()
    
    message_text = "📋 Список пользователей с подпиской:\n\n"
    if not subscribed_users:
        message_text = "📝 Активных подписок нет."
    else:
        for u in subscribed_users:
            message_text += f"🆔 ID: {u[0]} | До: {u[1]}\n"

    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_admin')]]
    await update.callback_query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ID

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_admin')]]
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text="📢 Введите сообщение для рассылки:", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROADCAST

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message.text
    cursor.execute('SELECT user_id FROM users')
    user_ids = cursor.fetchall()
    success, fail = 0, 0
    
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid[0], text=message)
            success += 1
        except Exception:
            fail += 1

    await update.message.reply_text(f'📊 Рассылка завершена\n✅ Успешно: {success}\n❌ Ошибок: {fail}')
    return ConversationHandler.END

async def back_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("✅ Выдать подписку", callback_data='grant_subscription')],
        [InlineKeyboardButton("❌ Снять подписку", callback_data='revoke_subscription')],
        [InlineKeyboardButton("📋 Список пользователей", callback_data='list_users')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='broadcast')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text('👨‍💻 Админ панель:', reply_markup=reply_markup)
    return ID


# --- ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА БОТА ---

def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()

    # ConversationHandler для Админки
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_panel)],
        states={
            ID: [
                CallbackQueryHandler(grant_subscription, pattern='^grant_subscription$'),
                CallbackQueryHandler(revoke_subscription, pattern='^revoke_subscription$'),
                CallbackQueryHandler(list_users, pattern='^list_users$'),
                CallbackQueryHandler(broadcast, pattern='^broadcast$'),
                CallbackQueryHandler(back_to_admin, pattern='^back_to_admin$')
            ],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, duration_handler)],
            CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmation_handler)],
            REMOVE_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_confirmation_handler)],
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_handler)]
        },
        fallbacks=[CommandHandler('admin', admin_panel)]
    )

    # ConversationHandler для функций бота (Активация, Репорт, Разбан)
    bot_actions_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_activate, pattern='^menu_activate$'),
            CallbackQueryHandler(start_report, pattern='^menu_report$'),
            CallbackQueryHandler(start_unban, pattern='^menu_unban$')
        ],
        states={
            ACTIVATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_activate)],
            REPORT_NICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_nick_handler)],
            REPORT_REASON_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_reason_handler)],
            REPORT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_finish_handler)],
            UNBAN_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_unban)]
        },
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(admin_conv)
    app.add_handler(bot_actions_conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🚀 Бот полностью запущен в режиме единого скрипта!")
    app.run_polling()

if __name__ == '__main__':
    main()
