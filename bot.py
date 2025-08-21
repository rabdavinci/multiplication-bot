import logging
import random
import asyncio
import time
import sqlite3
import os
from pathlib import Path
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext

# Настройка путей для Docker
BASE_DIR = Path(__file__).parent
DB_PATH = os.getenv('DB_PATH', 'multiplication_game.db')

# Простая настройка логирования
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required!")

# Achievement system
ACHIEVEMENTS = {
    'first_5': {'name': '🚀 Новичок', 'description': 'Решить 5 примеров'},
    'first_10': {'name': '⭐ Ученик', 'description': 'Решить 10 примеров'},
    'first_25': {'name': '🏆 Чемпион', 'description': 'Решить 25 примеров'},
    'first_50': {'name': '👑 Мастер', 'description': 'Решить 50 примеров'},
    'first_100': {'name': '🎯 Легенда', 'description': 'Решить 100 примеров'},
    'speed_10': {'name': '⚡ Скорострел', 'description': 'Ответить на 10 вопросов быстрее 5 секунд'},
    'accuracy_90': {'name': '🎯 Снайпер', 'description': 'Достичь точности 90%'},
}

def init_database():
    """Initialize the database with error handling"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            total_correct INTEGER DEFAULT 0,
            total_attempts INTEGER DEFAULT 0,
            total_points INTEGER DEFAULT 0,
            level TEXT DEFAULT 'Новичок',
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create achievements table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER,
            achievement_id TEXT,
            achieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, achievement_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # Create daily activity table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            points INTEGER,
            activity_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized successfully at: {DB_PATH}")
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

def get_user_level(points):
    """Determine user level based on points"""
    if points < 100:
        return "🎒 Новичок"
    elif points < 500:
        return "🎓 Ученик"
    elif points < 1000:
        return "🥉 Бронза"
    elif points < 2000:
        return "🥈 Серебро"
    elif points < 5000:
        return "🥇 Золото"
    else:
        return "💎 Алмаз"

def update_user_stats(user_id, username, first_name, last_name, correct=False, points=0):
    """Update user statistics in database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        if cursor.fetchone() is None:
            # Create new user
            chat_id = None
            try:
                chat_id = int(os.getenv('CURRENT_CHAT_ID', '0'))
            except:
                chat_id = 0
            cursor.execute('''
            INSERT INTO users (user_id, chat_id, username, first_name, last_name, total_correct, total_attempts, total_points)
            VALUES (?, ?, ?, ?, ?, 0, 0, 0)
            ''', (user_id, chat_id, username, first_name, last_name))
        
        # Update statistics
        if correct:
            cursor.execute('''
            UPDATE users 
            SET total_correct = total_correct + 1,
                total_attempts = total_attempts + 1,
                total_points = total_points + ?,
                level = ?,
                last_activity = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''', (points, get_user_level(points), user_id))
            
            # Record daily activity
            cursor.execute('''
            INSERT INTO user_activity (user_id, points)
            VALUES (?, ?)
            ''', (user_id, points))
        else:
            cursor.execute('''
            UPDATE users 
            SET total_attempts = total_attempts + 1,
                last_activity = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''', (user_id,))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error updating user stats: {e}")

def get_global_rating(limit=10):
    """Get global rating of top users"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT user_id, username, first_name, total_points, total_correct, total_attempts,
               CASE WHEN total_attempts > 0 THEN (total_correct * 100.0 / total_attempts) ELSE 0 END as accuracy
        FROM users 
        WHERE total_attempts >= 5
        ORDER BY total_points DESC 
        LIMIT ?
        ''', (limit,))
        
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        logger.error(f"Error getting global rating: {e}")
        return []

def get_user_rank(user_id):
    """Get user's global rank"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT COUNT(*) + 1 
        FROM users 
        WHERE total_points > (SELECT total_points FROM users WHERE user_id = ?)
        AND total_attempts >= 5
        ''', (user_id,))
        
        rank = cursor.fetchone()[0]
        conn.close()
        return rank
    except Exception as e:
        logger.error(f"Error getting user rank: {e}")
        return 0

def get_total_users():
    """Get total number of active users"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE total_attempts >= 5')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Error getting total users: {e}")
        return 0

def main_menu_keyboard():
    """Create main menu keyboard with Russian text"""
    keyboard = [
        [InlineKeyboardButton("Легкий (1-10) 🟢", callback_data='easy')],
        [InlineKeyboardButton("Средний (2-15) 🟡", callback_data='medium')],
        [InlineKeyboardButton("Сложный (5-50) 🔴", callback_data='hard')],
        [InlineKeyboardButton("Гений (10-100) 🧠", callback_data='genius')],
        [InlineKeyboardButton("Соревнование ⏱️", callback_data='competition')],
        [InlineKeyboardButton("Мой рейтинг 📊", callback_data='rating')],
        [InlineKeyboardButton("Топ игроков 🏆", callback_data='global_rating')],
        [InlineKeyboardButton("Достижения ⭐", callback_data='achievements')],
        [InlineKeyboardButton("Помощь ❓", callback_data='help')]
    ]
    return InlineKeyboardMarkup(keyboard)

def competition_mode_keyboard():
    """Keyboard for competition time selection"""
    keyboard = [
        [InlineKeyboardButton("30 секунд ⚡", callback_data='competition_30')],
        [InlineKeyboardButton("60 секунд 🏃‍♂️", callback_data='competition_60')],
        [InlineKeyboardButton("120 секунд 🏆", callback_data='competition_120')],
        [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def question_keyboard(answers, show_menu=True):
    """Create keyboard for question with answers"""
    keyboard = []
    for answer in answers:
        keyboard.append([InlineKeyboardButton(f"{answer}", callback_data=f'answer_{answer}')])
    
    if show_menu:
        keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')])
    
    return InlineKeyboardMarkup(keyboard)

def after_answer_keyboard(difficulty=None, competition=False):
    """Keyboard after answering a question"""
    keyboard = []
    if difficulty:
        keyboard.append([InlineKeyboardButton("➡️ Следующий вопрос", callback_data=f'next_{difficulty}')])
    
    if competition:
        keyboard.append([InlineKeyboardButton("🏁 Завершить соревнование", callback_data='finish_competition')])
    
    keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: CallbackContext) -> None:
    """Handle /start command with Russian text"""
    user = update.effective_user
    # Store chat_id for broadcast
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET chat_id = ? WHERE user_id = ?', (update.effective_chat.id, user.id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving chat_id: {e}")
    await update.message.reply_text(
        f"Привет {user.first_name}! 👋\n\n"
        "Я твой помощник в изучении таблицы умножения! 🧮\n"
        "Соревнуйся с другими игроками и поднимайся в рейтинге! 🏆\n\n"
        "Каждый месяц приз $10 за первое место в рейтинге! 🎁\n"
        "Следи за топом и участвуй!\n\n"
        "Выбери режим игры:",
        reply_markup=main_menu_keyboard()
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    """Show help in Russian"""
    help_text = (
        "🎮 Игра в таблицу умножения\n\n"
        "Как играть:\n"
        "• Выбери уровень сложности\n"
        "• Решай примеры на умножение\n"
        "• После ответа ты можешь выбрать следующий вопрос или вернуться в меню\n"
        "• Следи за своим прогрессом в рейтинге\n\n"
        "📊 Ты можешь проверять свой рейтинг в любое время!\n"
        "🏆 Соревнуйся с другими игроками!\n\n"
        "Режимы:\n"
        "• Обычный - учись в своем темпе\n"
        "• Соревнование - реши как можно больше за время\n\n"
        "Команды:\n"
        "/start - начать игру\n"
        "/rating - показать рейтинг\n"
        "/top - топ игроков\n"
        "/daily - ежедневный рейтинг\n"
        "/help - эта справка\n"
        "/reset - сбросить прогресс"
    )
    
    if update.message:
        await update.message.reply_text(help_text)
    else:
        await update.callback_query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
            ])
        )

async def reset_score(update: Update, context: CallbackContext) -> None:
    """Reset user's score with Russian message"""
    user = update.effective_user
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM users WHERE user_id = ?', (user.id,))
        cursor.execute('DELETE FROM achievements WHERE user_id = ?', (user.id,))
        cursor.execute('DELETE FROM user_activity WHERE user_id = ?', (user.id,))
        
        conn.commit()
        conn.close()
        
        if 'score' in context.user_data:
            context.user_data['score'] = {'correct': 0, 'total': 0, 'points': 0}
        if 'achievements' in context.user_data:
            context.user_data['achievements'] = {}
        if 'reaction_time' in context.user_data:
            context.user_data['reaction_time'] = []
        
        await update.message.reply_text("Прогресс сброшен! 🆕\nНачинаем заново! 🚀")
        
    except Exception as e:
        logger.error(f"Error resetting score: {e}")
        await update.message.reply_text("Ошибка при сбросе прогресса. Попробуйте позже.")

def generate_wrong_answers(correct_answer: int) -> list:
    """Generate plausible wrong answers"""
    wrong_answers = set()
    while len(wrong_answers) < 3:
        # Generate answers close to the correct one
        variation = random.randint(-max(5, correct_answer//2), max(5, correct_answer//2))
        if variation != 0:
            wrong_answer = correct_answer + variation
            if wrong_answer > 0 and wrong_answer != correct_answer:
                wrong_answers.add(wrong_answer)
    return list(wrong_answers)

async def create_question(update: Update, context: CallbackContext, mode: str, difficulty: str = None) -> None:
    """Create a multiplication question"""
    if mode == 'competition':
        # Start competition timer
        context.user_data['start_time'] = time.time()
        context.user_data['mode'] = 'competition'
        context.user_data['competition_counter'] = 0
        difficulty = 'medium'  # Default difficulty for competition
    
    # Difficulty ranges
    ranges = {
        'easy': (1, 10),
        'medium': (2, 15),
        'hard': (5, 50),
        'genius': (10, 100)
    }
    a, b = ranges[difficulty]
    # Genius: always hard multiplication or division
    if difficulty == 'genius':
        if random.random() < 0.5:
            # Division: ensure integer result
            divisor = random.randint(10, b)
            quotient = random.randint(10, b)
            dividend = divisor * quotient
            correct_answer = quotient
            question_text = f"🧠 Чему равно {dividend} ÷ {divisor}?"
        else:
            num1 = random.randint(a, b)
            num2 = random.randint(a, b)
            correct_answer = num1 * num2
            question_text = f"🧠 Что такое {num1} × {num2}?"
    else:
        # For other levels, keep previous logic
        if random.random() < 0.5:
            # Division: ensure integer result
            divisor = random.randint(max(2, a), b)
            quotient = random.randint(a, b)
            dividend = divisor * quotient
            correct_answer = quotient
            question_text = f"🧮 Чему равно {dividend} ÷ {divisor}?"
        else:
            num1 = random.randint(a, b)
            num2 = random.randint(a, b)
            correct_answer = num1 * num2
            question_text = f"🧮 Что такое {num1} × {num2}?"
    # Store correct answer and start time
    context.user_data['correct_answer'] = correct_answer
    context.user_data['current_difficulty'] = difficulty
    context.user_data['question_time'] = time.time()
    # Generate wrong answers
    wrong_answers = generate_wrong_answers(correct_answer)
    all_answers = wrong_answers + [correct_answer]
    random.shuffle(all_answers)
    if mode == 'competition':
        remaining_time = context.user_data['competition_duration'] - (time.time() - context.user_data['start_time'])
        question_text = f"⏱️ {int(remaining_time)}с | {question_text}"
    if update.callback_query:
        await update.callback_query.edit_message_text(
            question_text,
            reply_markup=question_keyboard(all_answers, show_menu=(mode != 'competition'))
        )
    else:
        await update.message.reply_text(
            question_text,
            reply_markup=question_keyboard(all_answers, show_menu=(mode != 'competition'))
        )

async def check_answer(update: Update, context: CallbackContext) -> None:
    """Check user's answer and update global stats"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_answer = int(query.data.split('_')[1])
    correct_answer = context.user_data.get('correct_answer', 0)
    start_time = context.user_data.get('question_time', time.time())
    answer_time = time.time() - start_time
    
    # Calculate points
    is_correct = user_answer == correct_answer
    points = max(10, int(50 - answer_time * 10)) if is_correct else 0
    
    # Update global statistics
    update_user_stats(
        user.id, user.username, user.first_name, user.last_name,
        is_correct, points
    )
    
    # Russian feedback messages
    if is_correct:
        correct_messages = [
            "✅ Правильно! Отлично! 🎉",
            "✅ Верно! Ты математический гений! 🧙‍♂️",
            "✅ Супер! Так держать! 🚀 +{} очков!",
            "✅ Браво! Ты быстро учишься! 🌟 +{} очков!",
            "✅ Фантастика! Звезда математики! ⭐ +{} очков!"
        ]
        message = random.choice(correct_messages).format(points)
        if answer_time < 3:
            message += " ⚡ Быстро!"
    else:
        incorrect_messages = [
            "❌ Почти! Правильный ответ {}. Попробуй еще! 💪",
            "❌ Не совсем! Это было {}. Следующий получится! 👍",
            "❌ Хорошая попытка! Правильно было {}. Продолжай! 🏃‍♂️",
            "❌ Близко! Ответ {}. Практика ведет к совершенству! 📚"
        ]
        message = random.choice(incorrect_messages).format(correct_answer)
    
    # Show global rank update if user has enough attempts
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT total_attempts FROM users WHERE user_id = ?', (user.id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] >= 5 and is_correct:
            global_rank = get_user_rank(user.id)
            total_users = get_total_users()
            message += f"\n\n🏆 Твой ранг: {global_rank}/{total_users}"
    except Exception as e:
        logger.error(f"Error showing rank: {e}")
    
    # Show answer result and options for next question
    difficulty = context.user_data.get('current_difficulty')
    is_competition = context.user_data.get('mode') == 'competition'
    
    await query.edit_message_text(
        message,
        reply_markup=after_answer_keyboard(difficulty, is_competition)
    )

async def next_question(update: Update, context: CallbackContext) -> None:
    """Handle next question request"""
    query = update.callback_query
    await query.answer()
    
    difficulty = query.data.split('_')[1]
    mode = context.user_data.get('mode', 'normal')
    
    await create_question(update, context, mode, difficulty)

async def show_global_rating(update: Update, context: CallbackContext) -> None:
    """Show global rating of top players"""
    top_players = get_global_rating(15)
    total_users = get_total_users()
    
    if not top_players:
        message = "🏆 Топ игроков\n\nПока никто не играл достаточно для рейтинга! Будь первым! 🚀"
    else:
        message = "🏆 ТОП-15 ИГРОКОВ\n\n"
        
        for i, (user_id, username, first_name, points, correct, attempts, accuracy) in enumerate(top_players, 1):
            display_name = first_name or username or f"Игрок {user_id}"
            if i <= 3:  # Top 3 get medals
                medals = ["🥇", "🥈", "🥉"]
                message += f"{medals[i-1]} {i}. {display_name} - {points} очков\n"
            else:
                message += f"{i}. {display_name} - {points} очков\n"
            
            message += f"   ✅ {correct}/{attempts} ({accuracy:.1f}%)\n\n"
        
        message += f"Всего активных игроков: {total_users} 👥"
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')],
            [InlineKeyboardButton("📊 Мой рейтинг", callback_data='rating')]
        ])
    )

async def show_rating(update: Update, context: CallbackContext) -> None:
    """Show user rating with global rank"""
    user = update.effective_user
    user_id = user.id
    
    # Get user stats from database
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
        SELECT total_correct, total_attempts, total_points, level 
        FROM users WHERE user_id = ?
        ''', (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            correct, attempts, points, level = result
            accuracy = (correct / attempts * 100) if attempts > 0 else 0
            global_rank = get_user_rank(user_id)
            total_users = get_total_users()
        else:
            correct, attempts, points, accuracy, global_rank, total_users = 0, 0, 0, 0, 0, 0
    except Exception as e:
        logger.error(f"Error getting user rating: {e}")
        correct, attempts, points, accuracy, global_rank, total_users = 0, 0, 0, 0, 0, 0
    
    message = (
        f"📊 ТВОЙ РЕЙТИНГ\n\n"
        f"🎯 Уровень: {level or '🎒 Новичок'}\n"
        f"⭐ Очки: {points}\n"
        f"🏆 Глобальный ранг: {global_rank}/{total_users}\n"
        f"✅ Правильно: {correct}\n"
        f"❌ Всего попыток: {attempts}\n"
        f"🎯 Точность: {accuracy:.1f}%\n\n"
    )
    
    if attempts == 0:
        message += "Давай начнем учиться! 🚀"
    elif global_rank <= 3:
        message += "Ты в тройке лучших! Супер! 🌟"
    elif global_rank <= 10:
        message += "Ты в топ-10! Отлично! ⭐"
    elif accuracy < 50:
        message += "Продолжай тренироваться! Ты становишься лучше! 💪"
    elif accuracy < 75:
        message += "Хороший прогресс! Так держать! 👍"
    else:
        message += "Отличная работа! Ты звезда математики! 🌟"
    
    keyboard = [
        [InlineKeyboardButton("🏆 Топ игроков", callback_data='global_rating')],
        [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')],
        [InlineKeyboardButton("🔄 Сбросить", callback_data='confirm_reset')]
    ]
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def daily_rating(update: Update, context: CallbackContext) -> None:
    """Show daily top players"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT u.user_id, u.username, u.first_name, SUM(ua.points) as daily_points
        FROM user_activity ua
        JOIN users u ON ua.user_id = u.user_id
        WHERE date(ua.activity_time) = date('now')
        GROUP BY ua.user_id 
        ORDER BY daily_points DESC 
        LIMIT 10
        ''')
        
        daily_top = cursor.fetchall()
        conn.close()
        
        if not daily_top:
            message = "📅 Сегодня еще никто не играл! Будь первым! 🚀"
        else:
            message = "📅 ТОП-10 ЗА СЕГОДНЯ\n\n"
            for i, (user_id, username, first_name, points) in enumerate(daily_top, 1):
                display_name = first_name or username or f"Игрок {user_id}"
                if i <= 3:
                    medals = ["🥇", "🥈", "🥉"]
                    message += f"{medals[i-1]} {i}. {display_name} - {points} очков\n"
                else:
                    message += f"{i}. {display_name} - {points} очков\n"
    except Exception as e:
        logger.error(f"Error getting daily rating: {e}")
        message = "Ошибка при получении ежедневного рейтинга."
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏆 Общий рейтинг", callback_data='global_rating')],
            [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
        ])
    )

async def show_achievements(update: Update, context: CallbackContext) -> None:
    """Show user achievements"""
    user = update.effective_user
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT achievement_id FROM achievements WHERE user_id = ?', (user.id,))
        user_achievements = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        message = "🏆 ТВОИ ДОСТИЖЕНИЯ\n\n"
        obtained = 0
        
        for key, achievement in ACHIEVEMENTS.items():
            if key in user_achievements:
                message += f"✅ {achievement['name']} - {achievement['description']}\n"
                obtained += 1
            else:
                message += f"🔒 {achievement['name']} - ???\n"
        
        message += f"\n🎯 Получено: {obtained}/{len(ACHIEVEMENTS)}"
        
    except Exception as e:
        logger.error(f"Error getting achievements: {e}")
        message = "Ошибка при получении достижений."
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
        ])
    )

async def finish_competition(update: Update, context: CallbackContext) -> None:
    """Finish competition mode"""
    counter = context.user_data.get('competition_counter', 0)
    duration = context.user_data.get('competition_duration', 60)
    
    message = (
        f"🏁 Соревнование завершено!\n\n"
        f"⏱️ Время: {duration} секунд\n"
        f"✅ Решено примеров: {counter}\n"
        f"📊 Скорость: {counter/duration:.1f} примеров/секунду\n\n"
    )
    
    if counter/duration > 1:
        message += "⚡ Невероятная скорость! Ты супер! 🚀"
    elif counter/duration > 0.5:
        message += "🏃‍♂️ Отличный темп! Так держать! 👍"
    else:
        message += "💪 Хорошая попытка! Тренируйся дальше! 🌟"
    
    context.user_data['mode'] = None
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Еще раз", callback_data='competition')],
            [InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]
        ])
    )

async def button_handler(update: Update, context: CallbackContext) -> None:
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data in ['easy', 'medium', 'hard', 'genius']:
        await create_question(update, context, 'normal', query.data)
    elif query.data == 'competition':
        await query.edit_message_text(
            "⏱️ Выбери длительность соревнования:",
            reply_markup=competition_mode_keyboard()
        )
    elif query.data.startswith('competition_'):
        duration = int(query.data.split('_')[1])
        context.user_data['competition_duration'] = duration
        await create_question(update, context, 'competition', 'medium')
    elif query.data == 'rating':
        await show_rating(update, context)
    elif query.data == 'global_rating':
        await show_global_rating(update, context)
    elif query.data == 'achievements':
        await show_achievements(update, context)
    elif query.data == 'help':
        await help_command(update, context)
    elif query.data == 'main_menu':
        context.user_data['mode'] = None
        await query.edit_message_text(
            "Выбери режим игры:",
            reply_markup=main_menu_keyboard()
        )
    elif query.data.startswith('next_'):
        await next_question(update, context)
    elif query.data == 'finish_competition':
        await finish_competition(update, context)
    elif query.data == 'confirm_reset':
        await confirm_reset(update, context)

async def confirm_reset(update: Update, context: CallbackContext) -> None:
    """Confirm reset with Russian text"""
    await update.callback_query.edit_message_text(
        "⚠️ Ты уверен, что хочешь сбросить свой прогресс?\nЭто действие нельзя отменить!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, сбросить", callback_data='reset_score')],
            [InlineKeyboardButton("❌ Отмена", callback_data='rating')]
        ])
    )

async def reset_score_button(update: Update, context: CallbackContext) -> None:
    """Reset score via button"""
    query = update.callback_query
    user = update.effective_user
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE user_id = ?', (user.id,))
        cursor.execute('DELETE FROM achievements WHERE user_id = ?', (user.id,))
        cursor.execute('DELETE FROM user_activity WHERE user_id = ?', (user.id,))
        conn.commit()
        conn.close()
        
        if 'score' in context.user_data:
            context.user_data['score'] = {'correct': 0, 'total': 0, 'points': 0}
        if 'achievements' in context.user_data:
            context.user_data['achievements'] = {}
        
        await query.edit_message_text("Прогресс сброшен! 🆕\nНачинаем заново! 🚀")
        await asyncio.sleep(2)
        await query.edit_message_text(
            "Выбери режим игры:",
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Error resetting score via button: {e}")
        await query.edit_message_text("Ошибка при сбросе прогресса.")

def main() -> None:
    """Start the bot"""
    try:
        # Initialize database
        init_database()
        
        # Create the Application
        application = Application.builder().token(TOKEN).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("rating", show_rating))
        application.add_handler(CommandHandler("top", show_global_rating))
        application.add_handler(CommandHandler("daily", daily_rating))
        application.add_handler(CommandHandler("reset", reset_score))
        
        # Add callback query handlers
        application.add_handler(CallbackQueryHandler(button_handler, pattern='^(easy|medium|hard|competition|rating|global_rating|achievements|help|main_menu|confirm_reset|finish_competition)$'))
        application.add_handler(CallbackQueryHandler(reset_score_button, pattern='^reset_score$'))
        application.add_handler(CallbackQueryHandler(button_handler, pattern='^competition_'))
        application.add_handler(CallbackQueryHandler(button_handler, pattern='^next_'))
        application.add_handler(CallbackQueryHandler(check_answer, pattern='^answer_'))
        
        # Start background tasks for daily and monthly notifications
        async def daily_top_broadcast():
            while True:
                await asyncio.sleep(60*60*24)  # Run once a day
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('SELECT user_id, chat_id FROM users WHERE chat_id IS NOT NULL')
                    users = cursor.fetchall()
                    top_players = get_global_rating(3)
                    if top_players:
                        msg = "🏆 Ежедневный ТОП-3 игроков:\n\n"
                        medals = ["🥇", "🥈", "🥉"]
                        for i, (user_id, username, first_name, points, correct, attempts, accuracy) in enumerate(top_players, 1):
                            name = first_name or username or f"Игрок {user_id}"
                            msg += f"{medals[i-1]} {name} — {points} очков\n"
                        for user_id, chat_id in users:
                            if chat_id:
                                try:
                                    await application.bot.send_message(chat_id, msg)
                                except Exception as e:
                                    logger.error(f"Broadcast error: {e}")
                    conn.close()
                except Exception as e:
                    logger.error(f"Daily broadcast error: {e}")
        async def monthly_prize_broadcast():
            while True:
                now = datetime.now()
                # Run at 23:59 on last day of month
                if now.day == 28 and now.hour == 23 and now.minute >= 59:  # For demo, use 28th
                    try:
                        conn = sqlite3.connect(DB_PATH)
                        cursor = conn.cursor()
                        cursor.execute('SELECT user_id, chat_id FROM users WHERE chat_id IS NOT NULL')
                        users = cursor.fetchall()
                        top_players = get_global_rating(1)
                        if top_players:
                            winner = top_players[0]
                            name = winner[2] or winner[1] or f"Игрок {winner[0]}"
                            msg = f"🎉 Поздравляем! {name} занял первое место в месячном рейтинге и получает приз $10! Свяжитесь с админом для получения приза."
                            chat_id = None
                            for user_id, c_id in users:
                                if user_id == winner[0]:
                                    chat_id = c_id
                                    break
                            if chat_id:
                                try:
                                    await application.bot.send_message(chat_id, msg)
                                except Exception as e:
                                    logger.error(f"Prize error: {e}")
                        conn.close()
                    except Exception as e:
                        logger.error(f"Monthly prize error: {e}")
                await asyncio.sleep(60)  # Check every minute
        # Start the Bot
        logger.info("Bot is starting...")
        print("Bot is starting...")
        print("Press Ctrl+C to stop the bot")
        # Start background tasks
        loop = asyncio.get_event_loop()
        loop.create_task(daily_top_broadcast())
        loop.create_task(monthly_prize_broadcast())
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Bot crashed with error: {e}")
        raise

if __name__ == "__main__":
    main()