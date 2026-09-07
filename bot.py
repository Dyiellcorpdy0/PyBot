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

ВАЖНО: Если ты замечаешь, что пользователь недоволен, конфликтует, жалуется или его вопрос не может быть решен через AI, 
ТЫ ДОЛЖЕН:
1. Сообщить пользователю: "Я понимаю ваше беспокойство. Администратор свяжется с вами в течение часа, чтобы решить ваш вопрос."
2. Собрать следующую информацию для администратора:
   - ID пользователя
   - Имя пользователя
   - Суть проблемы/конфликта
   - Последние сообщения диалога
   - Время обращения
3. Сгенерировать отчет в формате: "КОНФЛИКТ: [описание] | ПОЛЬЗОВАТЕЛЬ: [ID] [имя] | СООБЩЕНИЯ: [последние 3 сообщения] | ВРЕМЯ: [время]"
"""

# АКТУАЛЬНЫЕ БЕСПЛАТНЫЕ МОДЕЛИ НА OPENROUTER (на 2026 год)
AVAILABLE_MODELS = [
    "google/gemini-2.0-flash-lite-001",
    "google/gemini-flash-1.5",
    "mistralai/mistral-7b-instruct-v0.1",
    "meta-llama/llama-3.2-1b-instruct",
    "microsoft/phi-3.5-mini-128k-instruct",
    "qwen/qwen-2.5-0.5b-instruct",
]


current_model_index = 0


CONFLICT_KEYWORDS = [
    "жалоб", "недовол", "плох", "ужасн", "кошмар",
    "не работает", "ошибк", "не помог", "бесполезн",
    "не доволен", "разочаров", "проблем", "не устраива",
    "неправильн", "обман", "требую", "претенз",
    "ужасно", "отвратительн", "возмущ", "негод"
]


def get_current_model():
    """Получить текущую модель"""
    global current_model_index
    if current_model_index >= len(AVAILABLE_MODELS):
        current_model_index = 0
    return AVAILABLE_MODELS[current_model_index]


def switch_to_next_model():
    """Переключиться на следующую модель"""
    global current_model_index
    current_model_index = (current_model_index + 1) % len(AVAILABLE_MODELS)
    return get_current_model()


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


async def notify_admin_conflict(user_id: int, user_name: str, issue: str, conversation_history: list,
                                context: ContextTypes.DEFAULT_TYPE):
    """Отправить уведомление администратору о конфликте"""
    # Собираем последние сообщения (до 5 штук)
    last_messages = []
    for msg in conversation_history[-10:]:
        if msg["role"] in ["user", "assistant"]:
            role = "Пользователь" if msg["role"] == "user" else "AI"
            last_messages.append(f"{role}: {msg['content'][:200]}...")

    report = (
        f" **НОВЫЙ КОНФЛИКТ В CHATBOT!**\n\n"
        f" **Пользователь:** {user_name}\n"
        f" **ID:** {user_id}\n"
        f" **Описание:** {issue}\n"
        f" **Время:** {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f" **Последние сообщения:**\n"
        f"{chr(10).join(last_messages)}\n\n"
        f" Администратор должен связаться с пользователем в течение часа!"
    )

    # Сохраняем отчет
    conflict_reports[user_id] = {
        "time": datetime.now(),
        "report": report,
        "issue": issue,
        "user_name": user_name
    }

    # Отправляем всем администраторам
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=report,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")


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
            " Миссия: Сделать IT-образование доступным\n"
            " Мы находимся в Минске\n\n"
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


async def get_ai_response(messages: list, retry_count: int = 0) -> str:
    """Получение ответа от AI через OpenRouter с автоматической сменой модели при ошибке"""
    try:
        if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "sk-ваш_ключ_от_openrouter":
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

            async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["choices"][0]["message"]["content"]
                else:
                    error_text = await response.text()
                    logger.error(f"OpenRouter error with model {model}: {response.status} - {error_text}")

                    if (response.status == 404 or response.status == 400) and retry_count < len(AVAILABLE_MODELS):
                        switch_to_next_model()
                        logger.info(f"Switching to next model: {get_current_model()}")
                        return await get_ai_response(messages, retry_count + 1)

                    return f"Извините, все AI-модели временно недоступны. Попробуйте позже."
    except asyncio.TimeoutError:
        return " Превышено время ожидания ответа. Попробуйте позже."
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        if retry_count < len(AVAILABLE_MODELS):
            switch_to_next_model()
            logger.info(f"Switching to next model due to error: {get_current_model()}")
            return await get_ai_response(messages, retry_count + 1)
        return "Произошла ошибка. Попробуйте позже."


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений пользователя"""
    user_id = update.effective_user.id
    user_message = update.message.text
    user_name = update.effective_user.full_name or update.effective_user.username or str(user_id)

    if user_id not in user_conversations:
        user_conversations[user_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    await update.message.chat.send_action(action="typing")

    try:

        if detect_conflict(user_message):

            issue = f"Пользователь выразил недовольство: {user_message[:200]}"


            user_conversations[user_id].append(
                {"role": "user", "content": user_message}
            )

            # Уведомляем администратора
            await notify_admin_conflict(
                user_id=user_id,
                user_name=user_name,
                issue=issue,
                conversation_history=user_conversations[user_id],
                context=context
            )


            response = (
                "🙏 Я понимаю ваше беспокойство.\n\n"
                "Администратор IT School свяжется с вами в течение часа, "
                "чтобы решить ваш вопрос и помочь вам.\n\n"
                "Извините за доставленные неудобства. Мы ценим каждого ученика! 💙"
            )

            # Сохраняем ответ AI в историю
            user_conversations[user_id].append(
                {"role": "assistant", "content": response}
            )

            await update.message.reply_text(
                response,
                reply_markup=get_ai_keyboard()
            )
            return


        user_conversations[user_id].append(
            {"role": "user", "content": user_message}
        )

        response = await get_ai_response(user_conversations[user_id])


        if "администратор свяжется" in response.lower() or "в течение часа" in response.lower():

            await notify_admin_conflict(
                user_id=user_id,
                user_name=user_name,
                issue=f"AI обнаружил конфликтную ситуацию. Сообщение пользователя: {user_message[:200]}",
                conversation_history=user_conversations[user_id],
                context=context
            )

        await update.message.reply_text(
            response,
            reply_markup=get_ai_keyboard()
        )

        user_conversations[user_id].append(
            {"role": "assistant", "content": response}
        )

        if len(user_conversations[user_id]) > 21:
            user_conversations[user_id] = [
                                              {"role": "system", "content": SYSTEM_PROMPT}
                                          ] + user_conversations[user_id][-20:]

    except Exception as e:
        logger.error(f"Ошибка AI: {e}")

        # При ошибке тоже уведомляем администратора
        await notify_admin_conflict(
            user_id=user_id,
            user_name=user_name,
            issue=f"Техническая ошибка при обработке запроса: {str(e)[:200]}",
            conversation_history=user_conversations.get(user_id, []),
            context=context
        )

        await update.message.reply_text(
            " Извините, произошла ошибка при обработке запроса.\n"
            "Администратор уже уведомлен и свяжется с вами в ближайшее время.\n\n"
            "Попробуйте позже или обратитесь к администратору.",
            reply_markup=get_ai_keyboard()
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
        " История диалога очищена!",
        reply_markup=get_ai_keyboard()
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(" Доступ запрещен.")
        return

    current_model = get_current_model()
    stats_text = (
        f" **Статистика AI-помощника**\n\n"
        f" Пользователей: {len(user_conversations)}\n"
        f" Сообщений в истории: {sum(len(conv) for conv in user_conversations.values())}\n"
        f" Текущая модель: {current_model}\n"
        f" Доступно моделей: {len(AVAILABLE_MODELS)}\n"
        f" Конфликтов: {len(conflict_reports)}"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')


async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /reports - просмотр отчетов о конфликтах (только для админов)"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(" Доступ запрещен.")
        return

    if not conflict_reports:
        await update.message.reply_text(" Нет активных отчетов о конфликтах.")
        return

    # Показываем последние 5 отчетов
    reports_list = list(conflict_reports.items())[-5:]

    for uid, report_data in reports_list:
        await update.message.reply_text(
            f" **Отчет о конфликте**\n\n"
            f"{report_data['report']}",
            parse_mode='Markdown'
        )
        await asyncio.sleep(0.5)  # Небольшая задержка между сообщениями


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
        print(f" Доступные модели AI:")
        for i, model in enumerate(AVAILABLE_MODELS, 1):
            print(f"   {i}. {model}")
        print(f" Текущая модель: {get_current_model()}")
        print(f" Ключевые слова для обнаружения конфликтов: {CONFLICT_KEYWORDS}")
        print("=" * 50)

        application.run_polling()

    except Exception as e:
        print(f" Ошибка при запуске: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()