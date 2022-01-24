"""A telegram bot to check and track A2 exams registration"""

import os

import redis
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import unidecode

import check_a2_slots

UPDATE_INTERVAL = 20
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

old_data = check_a2_slots.get_schools_from_file()
REDIS = redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379'))


def check(update: Update, context: CallbackContext) -> None:
    schools = check_a2_slots.get_schools_from_file(cities_filter=[
        unidecode.unidecode(c).lower().capitalize() for c in context.args])
    message = check_a2_slots.diff_to_str(schools)
    update.message.reply_text(message)


def cities(update: Update, context: CallbackContext) -> None:
    schools = check_a2_slots.get_schools_from_file()
    all_cities = sorted(schools.keys())
    update.message.reply_text(f'Exam takes place in the following cities:\n{", ".join(all_cities)}')


def track(update: Update, context: CallbackContext) -> None:
    cities_str = ','.join(sorted([unidecode.unidecode(c).lower().capitalize() for c in context.args]))
    cities_msg = cities_str if cities_str else 'all cities'
    REDIS.set(update.effective_message.chat_id, cities_str)
    update.message.reply_text(f'You are tracking exam slots in {cities_msg}')


def notrack(update: Update, context: CallbackContext) -> None:
    REDIS.delete(update.effective_message.chat_id)
    update.message.reply_text(f'You are no longer subscribed for updates')


def inform_about_change(context: CallbackContext) -> None:
    global old_data
    subscribers = REDIS.keys(pattern='*')
    new_data = check_a2_slots.get_schools_from_file()
    if old_data and check_a2_slots.has_changes(new_data, old_data):
        for chat_id in subscribers:
            # NOTE(ivasilev) redis stores bytes, need to explicitly call decode to get strings
            chosen_cities = [c for c in REDIS.get(chat_id).decode('utf-8').split(',') if c.strip()]
            message = check_a2_slots.diff_to_str(new_data, old_data, chosen_cities)
            context.bot.send_message(chat_id=chat_id.decode('utf-8'), text=message or "No change")
    old_data = new_data


def run():
    updater = Updater(TOKEN)
    updater.dispatcher.add_handler(CommandHandler('check', check))
    updater.dispatcher.add_handler(CommandHandler('cities', cities))
    updater.dispatcher.add_handler(CommandHandler('track', track))
    updater.dispatcher.add_handler(CommandHandler('notrack', notrack))
    updater.job_queue.run_repeating(inform_about_change, interval=UPDATE_INTERVAL, first=0)
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    run()
