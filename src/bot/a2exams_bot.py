"""A telegram bot to check and track A2 exams registration"""

import copy
import datetime
import html
import json
import logging
import os
import traceback

import redis
import telegram
from telegram import ParseMode, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import unidecode

from checker import a2exams_checker
import utils

NOTIFICATIONS_PAUSED = False
UPDATE_INTERVAL = 20
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DEVELOPER_CHAT_ID = os.getenv('DEVELOPER_CHAT_ID')
EXAMS_CHANNEL = os.getenv('EXAMS_CHANNEL')

SCHOOLS_DATA = a2exams_checker.get_schools_from_file()
REDIS = redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379'))

# XXX FIXME This should not be there but can't think of a better way to get last update time for generic status
# Using a coroutine to get last fetched time is not an option
OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
LAST_FETCHED = os.path.join(OUTPUT_DIR, 'last_fetched.html')

FETCHER_DOWN_THRESHOLD = int(os.getenv('FETCHER_DOWN_THREASHOLD', '120'))
IS_FETCHER_OK = True

# set up logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _vet_requested_cities(user_requested_cities, source_of_truth=SCHOOLS_DATA):
    """Returns a tuple (cities_ok, cities_error) """
    requested_cities = [" ".join(map(lambda d: d.title(), unidecode.unidecode(c).lower().split(' ')))
                        for c in user_requested_cities]
    if requested_cities:
        invalid_options = set(requested_cities) - set(source_of_truth.keys())
        if invalid_options:
            cities_ok = sorted(set(requested_cities) - invalid_options)
            return (cities_ok, sorted(invalid_options))
        return (sorted(requested_cities), [])
    return ([], [])


def _dump_db_data():
    chat_ids = _get_all_subscribers()
    variations = {}
    for chat_id in chat_ids:
        cities_tracked = _get_tracked_cities_str(chat_id)
        try:
            variations[cities_tracked] += 1
        except KeyError:
            variations[cities_tracked] = 1
    return '\n'.join([f"{var}: {num} users" for var, num in variations.items()])


def _fetch_from_db(chat_id, as_list=False):
    val = REDIS.get(chat_id)
    if val is None:
        return [] if as_list else None
    # redis stores byte strings, decode before returning
    val = val.decode('utf-8')
    if as_list:
        val = val.split(',') if val else []
    return val


def _get_tracked_cities(chat_id):
    if REDIS.exists(chat_id):
        # NOTE(ivasilev) redis stores bytes, need to explicitly call decode to get strings
        return [c for c in _fetch_from_db(chat_id, as_list=True) if c.strip()]
    return []


def _get_tracked_cities_str(chat_id):
    if REDIS.exists(chat_id):
        return _fetch_from_db(chat_id) or "all cities"
    return ''


def _set_tracked_cities_str(chat_id, cities_str):
    REDIS.set(chat_id, cities_str)


def _unsubscribe(chat_id):
    REDIS.delete(chat_id)


def _get_all_subscribers():
    # NOTE(ivasilev) redis stores bytes, need to explicitly call decode to get strings
    if not NOTIFICATIONS_PAUSED:
        return [chat_id.decode('utf-8') for chat_id in REDIS.keys(pattern='*')]
    return [DEVELOPER_CHAT_ID]


def _is_admin(chat_id):
    return int(chat_id) == int(DEVELOPER_CHAT_ID)


def _parse_cities_args(context_args, source_of_truth=SCHOOLS_DATA):
    # NOTE(ivasilev) Stripping whitespaces is necessary for correct parsing of 'Praha   , Brno , Ceske budejovice'
    preprocessed_args = [city.strip() for city in " ".join(context_args).split(',') if city.strip()]
    return _vet_requested_cities(preprocessed_args, source_of_truth)


def check(update: Update, context: CallbackContext) -> None:
    requested_cities, error_cities = _parse_cities_args(context.args)
    error_msg = ''
    if error_cities:
        error_msg = f'No exams in {",".join(error_cities)}\n'
    schools = a2exams_checker.get_schools_from_file(cities_filter=requested_cities)
    msg = a2exams_checker.diff_to_str(schools, url_in_header=True)
    response = f'{error_msg}{msg}'
    if not response:
        # NOTE(ivasilev) That is a temporary warning message until issue #23 is resolved
        response = (
                'Since noon March 27, 2023 recaptcha has been introduced at the exams tracking page, as well as minor'
                ' layout changes. Checker would need to be adapted to this change, the progress can be tracked in https://github.com/fernflower/trvalypobytexamchecker/issues/23 .'
                'Estimated time to deliver a fix - by Apr, 3, 2023. Until then no updates will be shown.')
    update.effective_message.reply_text(response)


def cities(update: Update, context: CallbackContext) -> None:
    schools = a2exams_checker.get_schools_from_file()
    all_cities = sorted(schools.keys())
    update.effective_message.reply_text(f'Exam takes place in the following cities:\n{", ".join(all_cities)}')


def track(update: Update, context: CallbackContext) -> None:
    error_msg = ''
    requested_cities, error_cities = _parse_cities_args(context.args)
    cities_str = ','.join(sorted(requested_cities))
    if error_cities:
        error_msg = f'No exams in {",".join(error_cities)}\n'
    # update tracking information for the given user
    _set_tracked_cities_str(update.effective_message.chat_id, cities_str)
    msg = f'{error_msg}You are tracking exam slots in {cities_str or "all cities"}'
    update.effective_message.reply_text(msg)


def notrack(update: Update, context: CallbackContext) -> None:
    _unsubscribe(update.effective_message.chat_id)
    update.effective_message.reply_text(f'You are no longer subscribed for updates')


def mystatus(update: Update, context: CallbackContext) -> None:
    tracked_cities = _get_tracked_cities_str(update.effective_message.chat_id)
    message = ('You are not subscribed for any updates, to subscribe use /track' if not tracked_cities else
               f'You are subscribed for updates in {tracked_cities}')
    update.effective_message.reply_text(message)


def users(update: Update, context: CallbackContext) -> None:
    total_users = len(_get_all_subscribers())
    update.effective_message.reply_text(f'{total_users} users are subscribed for updates')


def _do_inform(context, chat_ids, new_state, prev_state):
    """Asynchronous status update for subscribers is done here"""
    for chat_id in chat_ids:
        chosen_cities = _get_tracked_cities(chat_id)
        message = a2exams_checker.diff_to_str(new_state, prev_state, chosen_cities, url_in_header=True)
        # if message is empty - then there is no change in chosen_cities, so no need to inform users
        try:
            if message:
                context.bot.send_message(chat_id=chat_id, text=message)
        except telegram.error.Unauthorized:
            # the user has unsubscribed for good - remove him from subscribers
            _unsubscribe(chat_id)
            logger.info(f'Removing {chat_id} from subscribers')
        except telegram.error.TelegramError as exc:
            logger.error(f'An error has occurred during sending a message to {chat_id}: {exc}')


def _send_update_to_channel(context: CallbackContext, new_state: dict, prev_state: dict) -> None:
    """A single message with update (all cities, no filtering) is done here"""
    message = a2exams_checker.diff_to_str(new_state, prev_state, url_in_header=True)
    if message:
        context.bot.send_message(chat_id=EXAMS_CHANNEL, text=message)


def inform_about_change(context: CallbackContext) -> None:
    global SCHOOLS_DATA
    new_data = a2exams_checker.get_schools_from_file()
    if not SCHOOLS_DATA or a2exams_checker.has_changes(new_data, SCHOOLS_DATA):
        # Now deep copy new_data and old_data for every subscriber to get the same update
        new_state = copy.deepcopy(new_data)
        prev_state = copy.deepcopy(SCHOOLS_DATA)
        logger.info(f'New state = {new_state}\nOld state = {prev_state}')
        # Send message to the channel
        _send_update_to_channel(context, new_state, prev_state)
        context.dispatcher.run_async(_do_inform, context, _get_all_subscribers(), new_state, prev_state)
        SCHOOLS_DATA = new_data


def admin_broadcast(update: Update, context: CallbackContext) -> None:
    if not _is_admin(update.effective_message.chat_id):
        update.effective_message.reply_text(f'This command is restricted for admin users only,'
                                            f'not for {update.effective_message.chat_id}')
    else:
        message = ' '.join(context.args)
        for chat_id in _get_all_subscribers():
            try:
                context.bot.send_message(chat_id=chat_id, text=message)
            except telegram.error.Unauthorized:
                _unsubscribe(chat_id)
                logger.info(f'User has stopped the bot - removing {chat_id} from subscribers')


def admin_pause(update: Update, context: CallbackContext) -> None:
    if not _is_admin(update.effective_message.chat_id):
        update.effective_message.reply_text('This command is restricted for admin users only')
    else:
        global NOTIFICATIONS_PAUSED
        NOTIFICATIONS_PAUSED = True
        context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text='Pausing notifications for all subscribers')


def admin_resume(update: Update, context: CallbackContext) -> None:
    if not _is_admin(update.effective_message.chat_id):
        update.effective_message.reply_text('This command is restricted for admin users only')
    else:
        global NOTIFICATIONS_PAUSED
        NOTIFICATIONS_PAUSED = False
        context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text='Resuming notifications for all subscribers')


def admin_status(update: Update, context: CallbackContext) -> None:
    if not _is_admin(update.effective_message.chat_id):
        update.effective_message.reply_text('This command is restricted for admin users only')
    else:
        # get timestamp of last_fetched file
        last_fetch_time = a2exams_checker.get_last_fetch_time_from_data(human_readable=True)
        msg = f'Last fetch time: {last_fetch_time}\nUser subscriptions:\n{_dump_db_data()}'
        context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=msg)


def track_fetcher_status(context: CallbackContext) -> None:
    global IS_FETCHER_OK
    # Only updates for a status change will be sent not to get swamped
    last_update_ts = a2exams_checker.get_last_fetch_time_from_data(human_readable=False)
    delta = int(datetime.datetime.now().timestamp()) - int(float(last_update_ts))
    if delta > FETCHER_DOWN_THRESHOLD:
        # we are in trouble, fetcher has been blocked or down for some time
        if IS_FETCHER_OK:
            last_fetch_time = a2exams_checker.get_last_fetch_time_from_data(human_readable=True)
            context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=f'Fetcher is down, last update happened {delta} seconds ago at {last_fetch_time}')
        IS_FETCHER_OK = False
    else:
        if not IS_FETCHER_OK:
            context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text='Fetcher is up')
        IS_FETCHER_OK = True


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
    updater.dispatcher.add_handler(CommandHandler('adminstatus', admin_status))
    updater.dispatcher.add_error_handler(error_handler)
    updater.job_queue.run_repeating(inform_about_change, interval=UPDATE_INTERVAL, first=0)
    updater.job_queue.run_repeating(track_fetcher_status, interval=UPDATE_INTERVAL, first=0)
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    run()
