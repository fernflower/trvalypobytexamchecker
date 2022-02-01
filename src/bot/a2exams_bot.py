"""A telegram bot to check and track A2 exams registration"""

import html
import json
import logging
import os
import traceback

import redis
from telegram import ParseMode, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import unidecode

from checker import a2exams_checker

NOTIFICATIONS_PAUSED = False
UPDATE_INTERVAL = 20
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DEVELOPER_CHAT_ID = os.getenv('DEVELOPER_CHAT_ID')

old_data = a2exams_checker.get_schools_from_file()
REDIS = redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379'))

logger = logging.getLogger(__name__)


def _vet_requested_cities(user_requested_cities):
    """Returns a tuple (cities_ok, cities_error) """
    requested_cities = [unidecode.unidecode(c).lower().capitalize() for c in user_requested_cities]
    if requested_cities:
        invalid_options = set(requested_cities) - set(old_data.keys())
        if invalid_options:
            cities_ok = sorted(set(requested_cities) - invalid_options)
            return (cities_ok, sorted(invalid_options))
        return (sorted(requested_cities), [])
    return ([], [])


def _get_tracked_cities_str(chat_id):
    if REDIS.exists(chat_id):
        # NOTE(ivasilev) redis stores bytes, need to explicitly call decode to get strings
        return REDIS.get(chat_id).decode('utf-8') or 'all cities'


def _set_tracked_cities_str(chat_id, cities_str):
    REDIS.set(chat_id, cities_str)


def _get_all_subscribers():
    # NOTE(ivasilev) redis stores bytes, need to explicitly call decode to get strings
    if not NOTIFICATIONS_PAUSED:
        return [chat_id.decode('utf-8') for chat_id in REDIS.keys(pattern='*')]
    return [DEVELOPER_CHAT_ID]


def _is_admin(chat_id):
    return int(chat_id) == int(DEVELOPER_CHAT_ID)


def check(update: Update, context: CallbackContext) -> None:
    requested_cities, error_cities = _vet_requested_cities(context.args)
    error_msg = ''
    if error_cities:
        error_msg = f'No exams in {",".join(error_cities)}\n'
    schools = a2exams_checker.get_schools_from_file(cities_filter=requested_cities)
    msg = a2exams_checker.diff_to_str(schools)
    update.message.reply_text(f'{error_msg}{msg}')


def cities(update: Update, context: CallbackContext) -> None:
    schools = a2exams_checker.get_schools_from_file()
    all_cities = sorted(schools.keys())
    update.message.reply_text(f'Exam takes place in the following cities:\n{", ".join(all_cities)}')


def track(update: Update, context: CallbackContext) -> None:
    error_msg = ''
    requested_cities, error_cities = _vet_requested_cities(context.args)
    cities_str = ','.join(sorted(requested_cities))
    if error_cities:
        error_msg = f'No exams in {",".join(error_cities)}\n'
    # update tracking information for the given user
    _set_tracked_cities_str(update.effective_message.chat_id, cities_str)
    msg = f'{error_msg}You are tracking exam slots in {cities_str or "all cities"}'
    update.message.reply_text(msg)


def notrack(update: Update, context: CallbackContext) -> None:
    REDIS.delete(update.effective_message.chat_id)
    update.message.reply_text(f'You are no longer subscribed for updates')


def mystatus(update: Update, context: CallbackContext) -> None:
    tracked_cities = _get_tracked_cities_str(update.effective_message.chat_id)
    message = ('You are not subscribed for any updates, to subscribe use /track' if not tracked_cities else
               f'You are subscribed for updates in {tracked_cities}')
    update.message.reply_text(message)


def users(update: Update, context: CallbackContext) -> None:
    total_users = len(_get_all_subscribers())
    update.message.reply_text(f'{total_users} users are subscribed for updates')


def inform_about_change(context: CallbackContext) -> None:
    global old_data
    subscribers = _get_all_subscribers()
    new_data = a2exams_checker.get_schools_from_file()
    if not old_data or a2exams_checker.has_changes(new_data, old_data):
        for chat_id in subscribers:
            chosen_cities = [c for c in _get_tracked_cities_str(chat_id).split(',') if c.strip()]
            message = a2exams_checker.diff_to_str(new_data, old_data, chosen_cities)
            context.bot.send_message(chat_id=chat_id, text=message or "No change")
    old_data = new_data


def admin_broadcast(update: Update, context: CallbackContext) -> None:
    if not _is_admin(update.effective_message.chat_id):
        update.message.reply_text(f'This command is restricted for admin users {DEVELOPER_CHAT_ID} only, not for {update.effective_message.chat_id}')
    else:
        message = ' '.join(context.args)
        for chat_id in _get_all_subscribers():
            context.bot.send_message(chat_id=chat_id, text=message)


def admin_pause(update: Update, context: CallbackContext) -> None:
    if not _is_admin(update.effective_message.chat_id):
        update.message.reply_text('This command is restricted for admin users only')
    else:
        global NOTIFICATIONS_PAUSED
        NOTIFICATIONS_PAUSED = True
        context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text='Pausing notifications for all subscribers')


def admin_resume(update: Update, context: CallbackContext) -> None:
    if not _is_admin(update.effective_message.chat_id):
        update.message.reply_text('This command is restricted for admin users only')
    else:
        global NOTIFICATIONS_PAUSED
        NOTIFICATIONS_PAUSED = False
        context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text='Resuming notifications for all subscribers')


# NOTE(ivasilev) Shamelessly borrowed from
# https://github.com/python-telegram-bot/python-telegram-bot/blob/master/examples/errorhandlerbot.py
def error_handler(update: object, context: CallbackContext) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f'An exception was raised while handling an update\n'
        f'<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}'
        '</pre>\n\n'
        f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n'
        f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n'
        f'<pre>{html.escape(tb_string)}</pre>'
    )

    # Finally, send the message
    context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML)


def run():
    updater = Updater(TOKEN)
    updater.dispatcher.add_handler(CommandHandler('check', check))
    updater.dispatcher.add_handler(CommandHandler('cities', cities))
    updater.dispatcher.add_handler(CommandHandler('track', track))
    updater.dispatcher.add_handler(CommandHandler('notrack', notrack))
    updater.dispatcher.add_handler(CommandHandler('mystatus', mystatus))
    updater.dispatcher.add_handler(CommandHandler('users', users))
    updater.dispatcher.add_handler(CommandHandler('adminbroadcast', admin_broadcast))
    updater.dispatcher.add_handler(CommandHandler('adminpause', admin_pause))
    updater.dispatcher.add_handler(CommandHandler('adminresume', admin_resume))
    updater.dispatcher.add_error_handler(error_handler)
    updater.job_queue.run_repeating(inform_about_change, interval=UPDATE_INTERVAL, first=0)
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    run()