import logging
import aiohttp
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8842524737:AAEoMyRLQWqO3LOggkDaFMlQ00b2-vKW46s"
ADMIN_IDS = [883080434]

OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Хранилище истории диалогов
user_conversations = {}
# Хранилище конфликтов для администратора
conflict_reports = {}

SYSTEM_PROMPT = """
Ты - AI-помощник IT School, школы современных технологий.
Твоя задача - помогать ученикам и потенциальным ученикам.

Ты знаешь следующую информацию о школе:
- Название: IT School
- Специализации: Программирование (Python, Kodu, Scratch), Разработка игр на платформе Unity, 
  Робототехника Lego, Arduino, 3D-моделирование
- Контакты: +375 (29) 871-76-12 , info@it-school.by
- Режим работы: Пн-Вс 10:00-18:00

Отвечай вежливо, профессионально и помогай решать вопросы учеников.

ВАЖНО: Если пользователь задает вопрос, который ты не знаешь, или проявляет недовольство:
1. НЕ говори, что администратор свяжется с ним сразу.
2. ВЕЖЛИВО попроси пользователя оставить контактные данные (имя, телефон или Telegram).
3. Скажи: "Я передам ваши контактные данные администратору, и он свяжется с вами в ближайшее время."
4. Если пользователь уже оставил контакты, поблагодари его и скажи, что администратор свяжется с ним.

Всегда будь вежливым и профессиональным. Помогай пользователям с общей информацией о школе.
"""

# ТОЛЬКО ЭТА МОДЕЛЬ
AVAILABLE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]

current_model_index = 0

CONFLICT_KEYWORDS = [
    "жалоб", "недовол", "плох", "ужасн", "кошмар",
    "не работает", "ошибк", "не помог", "бесполезн",
    "не доволен", "разочаров", "проблем", "не устраива",
    "неправильн", "обман", "требую", "претенз",
    "ужасно", "отвратительн", "возмущ", "негод"
]

# Ключевые слова для запроса администратора
ADMIN_REQUEST_KEYWORDS = [
    "администратор", "менеджер", "директор", "руководитель",
    "позвать", "позовите", "свяжите", "свяжись", "поговорить",
    "личный", "лично", "жаловаться", "претензия"
]


def get_current_model():
    """Получить текущую модель"""
    return AVAILABLE_MODELS[0]


def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📚 О школе", callback_data='about')],
        [InlineKeyboardButton("📝 Курсы", callback_data='courses')],
        [InlineKeyboardButton("🤖 Чат с AI", callback_data='ai_chat')],
        [InlineKeyboardButton("📞 Контакты", callback_data='contact')],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_ai_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔄 Очистить историю", callback_data='clear_history')],
        [InlineKeyboardButton("❓ Частые вопросы", callback_data='faq')],
        [InlineKeyboardButton("◀️ Назад", callback_data='back_to_main')],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    welcome_text = (
        f"🌟 Здравствуйте, {user.first_name}! 🌟\n\n"
        "Добро пожаловать в **IT School** - школу современных технологий! 🚀\n\n"
        "🤖 У нас есть AI-помощник! Задайте любой вопрос о школе!\n\n"
        "Выберите раздел:"
    )
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )


def detect_conflict(text: str) -> bool:
    """Определение конфликтной ситуации по тексту"""
    text_lower = text.lower()
    for keyword in CONFLICT_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


def detect_admin_request(text: str) -> bool:
    """Определение запроса на связь с администратором"""
    text_lower = text.lower()
    for keyword in ADMIN_REQUEST_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


async def request_contact_info(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str = ""):
    """Запросить контактные данные у пользователя"""
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name or update.effective_user.username or str(user_id)

    # Сохраняем состояние
    context.user_data['waiting_for_contact'] = True
    context.user_data['user_name'] = user_name
    context.user_data['reason'] = reason

    response = (
        "👋 Для того чтобы администратор мог связаться с вами, пожалуйста, укажите:\n\n"
        "📱 **Ваш номер телефона** (или напишите, что предпочитаете Telegram)\n"
        "👤 **Ваше имя**\n"
        "❓ **Кратко опишите вопрос**\n\n"
        "📝 Пример: \"Иван, +375291234567, хочу записаться на курс Python\"\n\n"
        "После получения контактов администратор свяжется с вами в ближайшее время ⏰"
    )

    await update.message.reply_text(
        response,
        reply_markup=get_ai_keyboard(),
        parse_mode='Markdown'
    )


async def handle_contact_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка контактных данных от пользователя"""
    user_id = update.effective_user.id
    user_message = update.message.text
    user_name = context.user_data.get('user_name', 'Неизвестно')
    reason = context.user_data.get('reason', 'Запрос на связь с администратором')

    # Собираем контактную информацию
    contact_info = {
        "user_id": user_id,
        "user_name": user_name,
        "contact": user_message,
        "reason": reason,
        "time": datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    }

    # Формируем отчет для администратора
    report = (
        f"🆕 **ЗАПРОС НА СВЯЗЬ С АДМИНИСТРАТОРОМ**\n\n"
        f"👤 **Пользователь:** {user_name}\n"
        f"🆔 **ID:** {user_id}\n"
        f"📱 **Контактные данные:**\n{user_message}\n\n"
        f"❓ **Причина запроса:** {reason}\n"
        f"⏰ **Время:** {contact_info['time']}\n\n"
        f"⚠️ Администратор должен связаться с пользователем в течение часа!"
    )

    # Сохраняем отчет
    conflict_reports[user_id] = {
        "time": datetime.now(),
        "report": report,
        "contact": user_message,
        "user_name": user_name,
        "reason": reason
    }

    # Отправляем администратору
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=report,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    # Очищаем состояние ожидания
    context.user_data['waiting_for_contact'] = False

    # Отвечаем пользователю
    await update.message.reply_text(
        "✅ **Спасибо! Ваши контакты переданы администратору.**\n\n"
        "Администратор свяжется с вами в ближайшее время ⏰\n\n"
        "Если у вас есть еще вопросы, вы можете продолжить общение с ботом 🤖",
        reply_markup=get_ai_keyboard(),
        parse_mode='Markdown'
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    if data == 'about':
        await query.edit_message_text(
            " **О школе IT School**\n\n"
            "Современная школа программирования!\n\n"
            " Миссия: Сделать IT-образование доступным\n\n"
            "Наши преимущества:\n"
            "• Опытные преподаватели-практики\n"
            "• Современные методики обучения\n"
            "• Удобное расписание\n"
            "• Сертификаты после окончания",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    elif data == 'courses':
        await query.edit_message_text(
            " **Наши курсы:**\n\n"
            " **Программирование:**\n"
            "• Python (с нуля до профи)\n"
            "• Kodu Game Lab (для детей)\n"
            "• Scratch (основы программирования)\n\n"
            " **Разработка игр:**\n"
            "• Unity 2D/3D\n"
            "• Игровой дизайн\n\n"
            " **Робототехника:**\n"
            "• Lego Mindstorms\n"
            "• Arduino\n\n"
            " **3D-моделирование:**\n"
            "• Blender\n"
            "• 3D-печать\n\n"
            " Стоимость уточняйте у менеджера!",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    elif data == 'contact':
        await query.edit_message_text(
            " **Контакты**\n\n"
            " Телефон: +375 (29) 871-76-12\n"
            " Email: info@it-school.by\n"
            " Сайт: www.itschool.by\n\n"
            " Режим работы: Пн-Вс 10:00-18:00",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    elif data == 'ai_chat':
        if user_id not in user_conversations:
            user_conversations[user_id] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
        await query.edit_message_text(
            " **AI-помощник IT School**\n\n"
            "Задайте мне любой вопрос о школе, курсах или программировании!\n"
            "Я всегда готов помочь! ",
            reply_markup=get_ai_keyboard(),
            parse_mode='Markdown'
        )
    elif data == 'clear_history':
        if user_id in user_conversations:
            user_conversations[user_id] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
        await query.edit_message_text(
            "🔄 История диалога очищена!\n\n"
            "Теперь вы можете начать новый разговор.",
            reply_markup=get_ai_keyboard()
        )
    elif data == 'faq':
        await query.edit_message_text(
            "❓ **Частые вопросы:**\n\n"
            "1️⃣ **Какие курсы есть?**\n"
            "Программирование, Разработка игр, Робототехника, 3D-моделирование\n\n"
            "2️⃣ **Как записаться на курс?**\n"
            "Напишите менеджеру по телефону или в соцсетях\n\n"
            "3️⃣ **Есть ли пробные уроки?**\n"
            "Да! Первое занятие бесплатно 🎉\n\n"
            "4️⃣ **Какой возраст учеников?**\n"
            "От 7 до 17 лет\n\n"
            "5️⃣ **Нужны ли знания программирования?**\n"
            "Нет, мы обучаем с нуля!",
            reply_markup=get_ai_keyboard(),
            parse_mode='Markdown'
        )
    elif data == 'back_to_main':
        await query.edit_message_text(
            "Выберите раздел:",
            reply_markup=get_main_keyboard()
        )


async def get_ai_response(messages: list) -> str:
    """Получение ответа от AI через OpenRouter"""
    try:
        if not OPENROUTER_API_KEY:
            return "⚠ API ключ не настроен.\n\nПолучите бесплатный ключ на openrouter.ai"

        model = get_current_model()

        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://it-school.by",
                "X-Title": "IT School Bot"
            }

            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 500,
                "temperature": 0.7
            }

            async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["choices"][0]["message"]["content"]
                else:
                    error_text = await response.text()
                    logger.error(f"OpenRouter error with model {model}: {response.status} - {error_text}")
                    return f"Извините, AI-модель временно недоступна. Попробуйте позже."
    except asyncio.TimeoutError:
        return "⏰ Превышено время ожидания ответа. Попробуйте позже."
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        return "Произошла ошибка. Попробуйте позже."


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений пользователя"""
    user_id = update.effective_user.id
    user_message = update.message.text
    user_name = update.effective_user.full_name or update.effective_user.username or str(user_id)

    # Проверяем, ждем ли мы контактные данные
    if context.user_data.get('waiting_for_contact'):
        await handle_contact_collection(update, context)
        return

    if user_id not in user_conversations:
        user_conversations[user_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    await update.message.chat.send_action(action="typing")

    try:
        # Проверяем запрос на администратора или конфликт
        if detect_admin_request(user_message) or detect_conflict(user_message):
            # Запрашиваем контактные данные
            reason = f"Запрос пользователя: {user_message[:200]}"
            await request_contact_info(update, context, reason)

            # Сохраняем сообщение пользователя в историю
            user_conversations[user_id].append(
                {"role": "user", "content": user_message}
            )
            return

        # Обычная обработка сообщения
        user_conversations[user_id].append(
            {"role": "user", "content": user_message}
        )

        response = await get_ai_response(user_conversations[user_id])

        # Проверяем, не сгенерировал ли AI ответ о необходимости администратора
        if ("администратор свяжется" in response.lower() or
                "в течение часа" in response.lower() or
                "передам администратору" in response.lower()):
            # Запрашиваем контакты вместо отправки сообщения о конфликте
            reason = f"AI определил необходимость связи с администратором. Запрос: {user_message[:200]}"
            await request_contact_info(update, context, reason)
            return

        await update.message.reply_text(
            response,
            reply_markup=get_ai_keyboard()
        )

        user_conversations[user_id].append(
            {"role": "assistant", "content": response}
        )

        # Ограничиваем историю
        if len(user_conversations[user_id]) > 21:
            user_conversations[user_id] = [
                                              {"role": "system", "content": SYSTEM_PROMPT}
                                          ] + user_conversations[user_id][-20:]

    except Exception as e:
        logger.error(f"Ошибка AI: {e}")

        # Вместо ошибки просим контакты
        await request_contact_info(
            update,
            context,
            f"Техническая ошибка при обработке запроса: {str(e)[:100]}"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = (
        " **Помощь по боту**\n\n"
        "• /start - Главное меню\n"
        "• /help - Эта справка\n"
        "• /clear - Очистить историю диалога\n"
        "• /admin - Статистика (только для админов)\n"
        "• /reports - Просмотр отчетов о конфликтах (только для админов)\n\n"
        " Просто напишите сообщение, и AI-помощник ответит вам!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /clear - очистить историю"""
    user_id = update.effective_user.id
    if user_id in user_conversations:
        user_conversations[user_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    await update.message.reply_text(
        "🔄 История диалога очищена!",
        reply_markup=get_ai_keyboard()
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Доступ запрещен.")
        return

    current_model = get_current_model()
    stats_text = (
        f" **Статистика AI-помощника**\n\n"
        f" Пользователей: {len(user_conversations)}\n"
        f" Сообщений в истории: {sum(len(conv) for conv in user_conversations.values())}\n"
        f" Текущая модель: {current_model}\n"
        f" Конфликтов: {len(conflict_reports)}"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')


async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /reports - просмотр отчетов о конфликтах (только для админов)"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Доступ запрещен.")
        return

    if not conflict_reports:
        await update.message.reply_text("📭 Нет активных отчетов о конфликтах.")
        return

    # Показываем последние 5 отчетов
    reports_list = list(conflict_reports.items())[-5:]

    for uid, report_data in reports_list:
        await update.message.reply_text(
            f" **Отчет о конфликте**\n\n"
            f"{report_data['report']}",
            parse_mode='Markdown'
        )
        await asyncio.sleep(0.5)


def main():
    """Запуск бота"""
    try:
        print(" Запуск бота...")

        application = Application.builder().token(TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("clear", clear_command))
        application.add_handler(CommandHandler("admin", admin_command))
        application.add_handler(CommandHandler("reports", reports_command))

        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        print("=" * 50)
        print(" Бот IT School с AI-помощником запущен!")
        print(f" Администраторы: {ADMIN_IDS}")
        print(f" Модель AI: {get_current_model()}")
        print(f" Ключевые слова для обнаружения конфликтов: {CONFLICT_KEYWORDS}")
        print("=" * 50)

        application.run_polling()

    except Exception as e:
        print(f" Ошибка при запуске: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()