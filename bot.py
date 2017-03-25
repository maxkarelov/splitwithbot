# coding: utf-8

from telegram.ext import Updater
from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, Filters
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ChatAction
import logging
import os
import time
from redis import StrictRedis
import psycopg2
import boto3
from botocore.client import Config
import requests
import json
import mimetypes

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

FINGER_UP = '👍🏻'
FINGER_DOWN = '👎🏻'
UP_ICON = '👍'
MAN_ICON = '🕵'
DONE_ICON = '✅'
ROBOT_ICON = '🤖'
PIZZA_ICON = '🍕'
CARD_ICON = '💳'
RESET_ICON = '🗑'
HAND_ICON = '✍'
EYES_ICON = '😳'

MODE = os.environ.get('MODE', 'polling')
URL = os.environ.get('URL')
TOKEN = os.environ.get('TOKEN')
PORT = int(os.environ.get('PORT', '5000'))
REDIS_URL = os.environ.get('REDIS_URL')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-central-1')
AWS_S3_BUCKET = os.environ.get('AWS_S3_BUCKET')
OCR_API_TOKEN = os.environ.get('OCR_API_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')
EXPIRATION = int(os.environ.get('EXPIRATION', 604800))
FEEDBACK_SESSION_EXPIRATION = 600

# redis hash keys templates
USER_KEY = 'user_{}'
CHAT_MESSAGE_OWNER_KEY = '{}_{}_owner'
CHAT_MESSAGE_STATUS_KEY = '{}_{}_status'
CHAT_MESSAGE_ITEMS_KEY = '{}_{}_items'
CHAT_MESSAGE_DONE_KEY = '{}_{}_done'
CHAT_MESSAGE_PAID_KEY = '{}_{}_paid'
CHAT_MESSAGE_ITEM_KEY = '{}_{}_{}'
CHAT_MESSAGE_ITEM_USERS_KEY = '{}_{}_{}_users'
FB_CHAT_USER_KEY = 'fb_{}_{}'

OPEN_STATUS = 'open'
WAIT_PAYMENTS_STATUS = 'wait_payments'
CLOSED_STATUS = 'closed'

DONE_BUTTON = 'done'
PAID_BUTTON = 'paid'
CLOSE_BUTTON = 'close'
RESET_BUTTON = 'reset'
PARSED_OK_BUTTON = 'parsed_ok'
PARSED_BAD_BUTTON = 'parsed_bad'

redis_client = StrictRedis.from_url(REDIS_URL, charset='utf-8', decode_responses=True)
postgres_conn = psycopg2.connect(DATABASE_URL)
db_cursor = postgres_conn.cursor()

updater = Updater(TOKEN)
dispatcher = updater.dispatcher


def parse_ocr_output(data):
  lines = data['ParsedResults'][0]['TextOverlay']['Lines']

  words = []

  for line in lines:
    for word in line['Words']:
      words.append({
        'text': word['WordText'],
        'left': word['Left'],
        'top': word['Top'],
        'height': word['Height'],
        'width': word['Width']
      })

  result = []

  for word in sorted(words, key=lambda k: k['top']):
    if len(result) == 0:
      result.append([word])
    else:
      is_found = False
      for i in range(0, len(result)):
        if abs(word['top'] - result[i][0]['top']) < 25:
          result[i].append(word)
          result[i] = sorted(result[i], key=lambda k: k['left'])
          is_found = True
          break
      if not is_found:
        result.append([word])

  # something wrong
  if len(result) > 10:
    return None, result

  pre_items = []

  try:
    for i in range(0, len(result)):
      columns = []
      for j in range(0, len(result[i])-1):
        if j == 0:
          columns.append(result[i][j]['left'])
          continue
        if abs(result[i][j]['left'] + result[i][j]['width'] - result[i][j+1]['left']) > 60:
          columns.append(result[i][j+1]['left'])

      item_name = ''
      item_num = ''
      item_price = ''

      if len(columns) == 3:
        for j in range(0, len(result[i])):
          if result[i][j]['left'] >= columns[2]:
            item_price += result[i][j]['text'] + ' '
          elif result[i][j]['left'] >= columns[1]:
            item_num += result[i][j]['text'] + ' '
          else:
            item_name += result[i][j]['text'] + ' '

        pre_items.append({
          'name': item_name.strip(),
          'num': int(float(item_num.strip().replace(',', '.').replace('о', '0').replace('o', '0').replace('()', '0'))),
          'price': int(float(item_price.strip().replace(',', '.').replace('о', '0').replace('o', '0').replace('()', '0')))
        })
  except:
    return None, result

  return pre_items, result


items = [
  {
    "id": '1',
    "name": "пицца мясная",
    "total": 530.0
  },
  {
    "id": '2',
    "name": "пицца гавайская",
    "total": 480.0
  },
  {
    "id": '3',
    "name": "сок 2л",
    "total": 120.0
  }
]

help_message = 'Чат бот для разделения общего чека между участниками чата\n\n' \
               'Для включения бота, отправьте в чат фото чека и потом отметьте позиции, которые вы хотите поделить\n\n' \
               'Нажмите <b>Я все!</b> и ждите, когда остальные отметятся\n\n' \
               'Потом тот, кто скинул чек подтвердит его, и бот расчитает для каждого сумму, которую нужно перевести\n\n' \
               'Нажми <b>Я оплатил!</b> и бот закроет ваш перевод'

init_message = '<b>{} Проверь, правильно ли я распознал чек</b>\n\n'.format(EYES_ICON)

sorry_message = '<b>Мы рассмотрим этот случай.</b>\n\n' \
                'Ты можешь написать отзыв командой /feedback и описать, любую критику и пожелания.\n\n' \
                '<b>Для лучшего распознавания необходимо:</b>\n' \
                '1. Расправить чек\n' \
                '2. Сфотографировать при достаточном количестве света\n' \
                '3. Сразу обрезать лишние поля чека, чтобы на фото попали только позиции и цены\n' \
                '4. Проверить, что изображение снято вертикально\n\n' \
                'Простой пример:'

start_message = MAN_ICON + ' Разделить чек\n\n' \
                '1. Каждый кликает по позициям, которые хочет поделить\n' \
                '2. Потом нажимает <b>Я все!</b>\n' \
                '3. В конце владелец чека нажимает <b>Закрыть</b>\n' \
                '4. Все перекидывают средства и нажимают <b>Я перевел!</b>\n' \
                '5. Вот и все!'


def start(bot, update):
  bot.sendMessage(chat_id=update.message.chat_id, text=help_message, parse_mode='HTML')


def handle_receipt(bot, update):

  chat_id = update.message.chat_id
  message_id = update.message.message_id + 1

  timestamp = int(time.time())
  file_name = '{}_{}_{}.png'.format(chat_id, message_id, timestamp)
  file_path = '/tmp/{}'.format(file_name)

  new_file = bot.getFile(update.message.photo[-1].file_id)
  new_file.download(file_path)

  mime_type = mimetypes.guess_type(file_path)

  s3 = boto3.resource('s3', config=Config(signature_version='s3v4'))
  data = open(file_path, 'rb')
  s3.Bucket(AWS_S3_BUCKET).put_object(Key=file_name, Body=data, ContentType=mime_type[0], ACL='public-read')
  url = 'https://s3.{}.amazonaws.com/{}/{}'.format(AWS_REGION, AWS_S3_BUCKET, file_name)

  r = requests.get('https://api.ocr.space/parse/ImageUrl?apiKey={}&language=rus&isOverlayRequired=true&url={}'
                   .format(OCR_API_TOKEN, url))
  json_data = json.loads(r.text)

  raw_items, raw_json = parse_ocr_output(json_data)
  content = ''

  inline_buttons = []

  if raw_items:
    item_ind = 0
    for item in raw_items:
      for k in range(item['num']):
        content += '<b>{}</b> - {} руб.\n'.format(item['name'], item['price'])
        redis_client.sadd(CHAT_MESSAGE_ITEMS_KEY.format(chat_id, message_id), item_ind)
        redis_client.expire(CHAT_MESSAGE_ITEMS_KEY.format(chat_id, message_id), EXPIRATION)
        redis_client.hset(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item_ind), 'name', item['name'])
        redis_client.hset(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item_ind), 'price', item['price'])
        redis_client.expire(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item_ind), EXPIRATION)
        item_ind += 1
    inline_buttons.append([InlineKeyboardButton('{} Правильно!'.format(FINGER_UP), callback_data=PARSED_OK_BUTTON)])
  else:
    content += 'К сожалению, на данный момент мы не можем прочитать этот чек.\n\n' \
               'Нажмите <b>Неточно</b>, чтобы нам пришло уведомление по данному случаю.\n\n' \
               'Вы можете оставить отзыв или комментарий командой /feedback\n\n'

    content += '[DEBUG]\n'
    for line in raw_json:
      item_text = ''
      for word in line:
        item_text += '{} '.format(word['text'])
      content += '{}\n'.format(item_text)

  inline_buttons.append([InlineKeyboardButton('{}       Неточно'.format(FINGER_DOWN), callback_data=PARSED_BAD_BUTTON)])

  message_text = init_message
  message_text += content

  bot.sendChatAction(chat_id, ChatAction.TYPING)

  owner_id = update.message.from_user.id
  owner_username = update.message.from_user.username
  owner_first_name = update.message.from_user.first_name
  owner_last_name = update.message.from_user.last_name

  redis_client.hset(USER_KEY.format(owner_id), 'un', owner_username)
  redis_client.hset(USER_KEY.format(owner_id), 'fn', owner_first_name)
  redis_client.hset(USER_KEY.format(owner_id), 'ln', owner_last_name)

  redis_client.set(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id), owner_id)
  redis_client.expire(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id), EXPIRATION)
  redis_client.set(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), 'open')
  redis_client.expire(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), EXPIRATION)

  bot.sendMessage(chat_id=chat_id, text=message_text, parse_mode='HTML',
                  reply_markup=InlineKeyboardMarkup(inline_buttons))


def button_click(bot, update):
  query = update.callback_query

  user_id = query.from_user.id
  user_username = query.from_user.username
  user_first_name = query.from_user.first_name
  user_last_name = query.from_user.last_name

  chat_id = query.message.chat_id
  message_id = query.message.message_id

  button_key = query.data

  inline_buttons = [[InlineKeyboardButton('{} Я все!'.format(DONE_ICON), callback_data=DONE_BUTTON)],
                   [InlineKeyboardButton('{} Сбросить'.format(RESET_ICON), callback_data=RESET_BUTTON)],
                   [InlineKeyboardButton('{} Закрыть'.format(HAND_ICON), callback_data=CLOSE_BUTTON)]]

  redis_client.hset(USER_KEY.format(user_id), 'un', user_username)
  redis_client.hset(USER_KEY.format(user_id), 'fn', user_first_name)
  redis_client.hset(USER_KEY.format(user_id), 'ln', user_last_name)

  item_ids = redis_client.smembers(CHAT_MESSAGE_ITEMS_KEY.format(chat_id, message_id))

  update_time = '<i>обновлено {}</i>'.format(time.strftime('%I:%M %d/%m'))

  if button_key == PAID_BUTTON or button_key == CLOSE_BUTTON:
    if button_key == PAID_BUTTON:
      owner_id = redis_client.get(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id))
      if int(owner_id) == int(user_id):
        bot.answerCallbackQuery(update.callback_query.id, 'нельзя перевести самому себе')
        return
      else:
        bot.answerCallbackQuery(update.callback_query.id, 'оплата отмечена')

      paid_ids = redis_client.smembers(CHAT_MESSAGE_PAID_KEY.format(chat_id, message_id))

      if str(user_id) not in paid_ids:
        paid_ids.add(str(user_id))
        redis_client.sadd(CHAT_MESSAGE_PAID_KEY.format(chat_id, message_id), user_id)
        redis_client.expire(CHAT_MESSAGE_PAID_KEY.format(chat_id, message_id), EXPIRATION)

        owner_id = redis_client.get(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id))
        owner_username = redis_client.hget(USER_KEY.format(owner_id), 'un')
        owner_first_name = redis_client.hget(USER_KEY.format(owner_id), 'fn')
        owner_last_name = redis_client.hget(USER_KEY.format(owner_id), 'ln')

        from_username = redis_client.hget(USER_KEY.format(user_id), 'un')
        from_first_name = redis_client.hget(USER_KEY.format(user_id), 'fn')
        from_last_name = redis_client.hget(USER_KEY.format(user_id), 'ln')

        message_text = '@{} ({} {}) перевел @{} ({} {})'.format(from_username, from_first_name, from_last_name,
                                                                owner_username, owner_first_name, owner_last_name)
        bot.sendMessage(chat_id=chat_id, text=message_text, parse_mode='HTML')
      else:
        return

      user_ids = redis_client.smembers(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id))

      if len(paid_ids)+1 == len(user_ids):
        redis_client.set(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), CLOSED_STATUS)
        redis_client.expire(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), EXPIRATION)
        bot.editMessageText(text='<b>Чек закрыт</b>\n\nОставьте комментарий о работе и функциональности бота по команде /feedback',
                            chat_id=chat_id,
                            message_id=message_id, parse_mode='HTML')
        return

    owner_id = redis_client.get(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id))

    if button_key == CLOSE_BUTTON:
      done_user_ids = redis_client.smembers(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id))
      if int(owner_id) != int(user_id):
        bot.answerCallbackQuery(update.callback_query.id, 'закрыть может только тот, кто платил')
        return
      if len(done_user_ids) < 2:
        bot.answerCallbackQuery(update.callback_query.id, 'ни с кем не поделился')
        return
      redis_client.set(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), WAIT_PAYMENTS_STATUS)
      redis_client.expire(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), EXPIRATION)

    owner_username = redis_client.hget(USER_KEY.format(owner_id), 'un')
    owner_first_name = redis_client.hget(USER_KEY.format(owner_id), 'fn')
    owner_last_name = redis_client.hget(USER_KEY.format(owner_id), 'ln')

    users = {}

    item_ids = redis_client.smembers(CHAT_MESSAGE_ITEMS_KEY.format(chat_id, message_id))
    for item_id in item_ids:
      item_price = float(redis_client.hget(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item_id), 'price'))
      item_users = redis_client.smembers(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, item_id))

      price_per_user = int(item_price / len(item_users))

      for user_id in item_users:
        if user_id not in users.keys():
          username = redis_client.hget(USER_KEY.format(user_id), 'un')
          first_name = redis_client.hget(USER_KEY.format(user_id), 'fn')
          last_name = redis_client.hget(USER_KEY.format(user_id), 'ln')

          users[user_id] = {
            'un': username,
            'fn': first_name,
            'ln': last_name,
            'total': 0
          }

        users[user_id]['total'] += price_per_user

    paid_user_ids = redis_client.smembers(CHAT_MESSAGE_PAID_KEY.format(chat_id, message_id))
    done_user_ids = redis_client.smembers(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id))
    left_user_ids = done_user_ids - paid_user_ids

    message_text = 'Переведите @{} ({} {})\n\n'.format(owner_username, owner_first_name, owner_last_name)

    for user_id in left_user_ids:
      if int(user_id) != int(owner_id):
        message_text += '@{} ({} {}) - <b>{}</b> руб.\n'.format(users[user_id]['un'], users[user_id]['fn'],
                                                                users[user_id]['ln'], users[user_id]['total'])

    if len(paid_user_ids) > 0:
      message_text += '\nУже перевели:\n'
      for user_id in paid_user_ids:
        message_text += '@{} ({} {}) - <b>{}</b> руб.\n'.format(users[user_id]['un'], users[user_id]['fn'],
                                                                users[user_id]['ln'], users[user_id]['total'])
    message_text += '\n'

    inline_buttons = [[InlineKeyboardButton('{} через Тинькоф'.format(CARD_ICON), url='https://goo.gl/63JQi9')],
                      [InlineKeyboardButton('{} через Альфа Банк'.format(CARD_ICON), url='https://goo.gl/4SlQFh')],
                      [InlineKeyboardButton('{} через Яндекс Деньги'.format(CARD_ICON), url='https://goo.gl/UyxLnY')],
                      [InlineKeyboardButton('{} через ВТБ'.format(CARD_ICON), url='https://goo.gl/Ns8vAD')],
                      [InlineKeyboardButton('{} Я уже оплатил!'.format(UP_ICON), callback_data=PAID_BUTTON)]]

    message_text += update_time

    bot.editMessageText(text=message_text, chat_id=chat_id,
                        message_id=message_id, parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(inline_buttons))
    return
  elif button_key == DONE_BUTTON:
    bot.answerCallbackQuery(update.callback_query.id, 'отметился в чеке'
                            .format(user_username, user_first_name, user_last_name))
    redis_client.sadd(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id), user_id)
    redis_client.expire(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id), EXPIRATION)
  elif button_key == RESET_BUTTON:
    bot.answerCallbackQuery(update.callback_query.id, 'сбросил'
                            .format(user_username, user_first_name, user_last_name))
    redis_client.srem(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id), user_id)
    for item_id in item_ids:
      redis_client.srem(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, item_id), user_id)
    redis_client.srem(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, item_id), EXPIRATION)
  elif button_key == PARSED_OK_BUTTON:
    owner_id = redis_client.get(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id))
    if int(owner_id) == int(user_id):
      bot.answerCallbackQuery(update.callback_query.id, 'чек создан'
                              .format(user_username, user_first_name, user_last_name))
    else:
      bot.answerCallbackQuery(update.callback_query.id, 'может нажать только создатель')
      return
  elif button_key == PARSED_BAD_BUTTON:
    owner_id = redis_client.get(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id))
    if int(owner_id) == int(user_id):
      db_cursor.execute("""INSERT INTO report (user_id, username, first_name, last_name, chat_id, message_id, url, date)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())""",
                        (user_id, user_username, user_first_name, user_last_name, chat_id, message_id, None))
      postgres_conn.commit()
      bot.editMessageText(text=sorry_message, chat_id=chat_id,
                          message_id=message_id, parse_mode='HTML')
      bot.sendPhoto(chat_id=chat_id, photo='https://s3.eu-central-1.amazonaws.com/splitwithbot/receipt_simple_sample.png')
    else:
      bot.answerCallbackQuery(update.callback_query.id, 'может нажать только создатель')
    return
  else:
    item_name = redis_client.hget(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, button_key), 'name')
    bot.answerCallbackQuery(update.callback_query.id, 'выбрано'
                            .format(user_username, user_first_name, user_last_name, item_name))
    redis_client.sadd(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, button_key), user_id)
    redis_client.expire(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, button_key), EXPIRATION)

  users = {}

  message_text = '{} Разделить чек\n\n'.format(MAN_ICON)

  for item_id in item_ids:
    item_id = int(float(item_id))

    item_name = redis_client.hget(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item_id), 'name')
    item_price = float(redis_client.hget(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item_id), 'price'))

    message_text += '{} {} (<b>{}</b> руб.)\n'.format(PIZZA_ICON, item_name, int(item_price))

    item_user_ids = redis_client.smembers(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, item_id))
    for user_id in item_user_ids:
      if user_id not in users.keys():
        owner_username = redis_client.hget(USER_KEY.format(user_id), 'un')
        owner_first_name = redis_client.hget(USER_KEY.format(user_id), 'fn')
        owner_last_name = redis_client.hget(USER_KEY.format(user_id), 'ln')

        users[user_id] = {
          'un': owner_username,
          'fn': owner_first_name,
          'ln': owner_last_name,
          'total': 0
        }
      price_per_user = int(item_price / len(item_user_ids))
      users[user_id]['total'] += price_per_user
      message_text += '@{} ({} {}) - {} руб.\n'.format(users[user_id]['un'], users[user_id]['fn'],
                                                       users[user_id]['ln'], price_per_user)

    inline_buttons.append([InlineKeyboardButton('{} {}'.format(item_name, int(item_price)), callback_data=str(item_id))])
    message_text += '\n'

  done_user_ids = redis_client.smembers(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id))
  if len(done_user_ids):
    message_text += 'Уже отметились:\n'
    for user_id in done_user_ids:
      message_text += '{} @{} ({} {}) - <b>{}</b> руб.\n'.format(DONE_ICON, users[user_id]['un'], users[user_id]['fn'], users[user_id]['ln'], users[user_id]['total'])

    message_text += '\n'

  update_time = '<i>обновлено {}</i>'.format(time.strftime('%I:%M %d/%m'))

  bot.editMessageText(text='{} {}'.format(message_text, update_time),
                      chat_id=chat_id,
                      message_id=message_id,
                      parse_mode='HTML',
                      reply_markup=InlineKeyboardMarkup(inline_buttons))


def feedback(bot, update):
  chat_id = update.message.chat_id
  message_id = update.message.message_id
  user_id = update.message.from_user.id
  first_name = update.message.from_user.first_name

  message_text = ''
  if first_name:
    message_text += '<b>{}</b>, спасибо за участие в улучшении бота.\n'.format(first_name)
  else:
    message_text += 'Спасибо за участие в улучшении бота.\n'

  message_text += 'В следующем сообщении оставьте свой отзыв.\n\n' \
                 'Если вы можете сообщить более детально что-либо,\n' \
                 'напишите об этом и команда разработчков свяжется с вами. 😉'

  redis_client.set(FB_CHAT_USER_KEY.format(chat_id, user_id), message_id)
  redis_client.expire(FB_CHAT_USER_KEY.format(chat_id, user_id), FEEDBACK_SESSION_EXPIRATION)
  bot.sendMessage(chat_id=chat_id, parse_mode='HTML', text=message_text)


def message(bot, update):
  chat_id = update.message.chat_id
  message_id = update.message.message_id
  user_id = update.message.from_user.id
  username = update.message.from_user.username
  first_name = update.message.from_user.first_name
  last_name = update.message.from_user.last_name
  message_text = update.message.text

  check_message_id = redis_client.get(FB_CHAT_USER_KEY.format(chat_id, user_id))

  if check_message_id and message_id - int(check_message_id) < 30:
    db_cursor.execute("""INSERT INTO feedback (user_id, username, first_name, last_name, chat_id, message_id, text, date)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())""",
                      (user_id, username, first_name, last_name, chat_id, message_id, message_text))
    postgres_conn.commit()
    redis_client.delete(FB_CHAT_USER_KEY.format(chat_id, user_id))
    bot.sendMessage(chat_id=update.message.chat_id, text='{} Спасибо за отзыв!'.format(ROBOT_ICON))
  return


def error_callback(bot, update, error):
  try:
    raise error
  except Exception as e:
    print(e)


dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CommandHandler('help', start))
dispatcher.add_handler(CommandHandler('feedback', feedback))
dispatcher.add_handler(MessageHandler(Filters.text, message))
dispatcher.add_handler(MessageHandler(Filters.photo, handle_receipt))
dispatcher.add_handler(CallbackQueryHandler(button_click))
dispatcher.add_error_handler(error_callback)

if MODE == 'webhook':
  updater.start_webhook(listen='0.0.0.0', port=PORT, url_path=TOKEN)
  updater.bot.setWebhook(URL + '/' + TOKEN)
  updater.idle()
else:
  updater.start_polling()
