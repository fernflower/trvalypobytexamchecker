"""A telegram bot to check and track A2 exams registration"""

import os

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import unidecode

import check_a2_slots

UPDATE_INTERVAL = 20
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

old_data = check_a2_slots.get_schools_from_file()


def check(update: Update, context: CallbackContext) -> None:
    schools = check_a2_slots.get_schools_from_file(cities_filter=[
        unidecode.unidecode(c).lower().capitalize() for c in context.args])
    message = check_a2_slots.diff_to_str(schools)
    update.message.reply_text(message)


def cities(update: Update, context: CallbackContext) -> None:
    schools = check_a2_slots.get_schools_from_file()
    all_cities = sorted(schools.keys())
    update.message.reply_text(f'Exam takes place in the following cities:\n{", ".join(all_cities)}')


def inform_about_change(context: CallbackContext) -> None:
    global old_data
    # XXX FIXME Will be taken from redis
    subscribers = [('129963852', [])]
    new_data = check_a2_slots.get_schools_from_file()
    if old_data and check_a2_slots.has_changes(new_data, old_data):
        for chat_id, chosen_cities in subscribers:
            message = check_a2_slots.diff_to_str(new_data, old_data, chosen_cities)
            context.bot.send_message(chat_id=chat_id, text=message or "No change")
    old_data = new_data


def run():
    updater = Updater(TOKEN)
    updater.dispatcher.add_handler(CommandHandler('check', check))
    updater.dispatcher.add_handler(CommandHandler('cities', cities))
    updater.job_queue.run_repeating(inform_about_change, interval=UPDATE_INTERVAL, first=0)
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    run()
