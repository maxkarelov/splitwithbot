# coding: utf-8

from telegram.ext import Updater
from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, Filters
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import os
import time
from redis import StrictRedis
import boto3
from botocore.client import Config
import requests
import json
import mimetypes

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

UP_ICON = '👍'
MAN_ICON = '🕵'
DONE_ICON = '✅'
ROBOT_ICON = '🤖'
PIZZA_ICON = '🍕'
CARD_ICON = '💳'
RESET_ICON = '🗑'
HAND_ICON = '✍'

MODE = os.environ.get('MODE', 'polling')
URL = os.environ.get('URL')
TOKEN = os.environ.get('TOKEN')
PORT = int(os.environ.get('PORT', '5000'))
REDIS_URL = os.environ.get('REDIS_URL')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-central-1')
AWS_S3_BUCKET = os.environ.get('AWS_S3_BUCKET')
OCR_API_TOKEN = os.environ.get('OCR_API_TOKEN')

EXPIRATION = int(os.environ.get('EXPIRATION', 604800))

# redis hash keys templates
USER_KEY = 'user_{}'
CHAT_MESSAGE_OWNER_KEY = '{}_{}_owner'
CHAT_MESSAGE_STATUS_KEY = '{}_{}_status'
CHAT_MESSAGE_ITEMS_KEY = '{}_{}_items'
CHAT_MESSAGE_DONE_KEY = '{}_{}_done'
CHAT_MESSAGE_PAID_KEY = '{}_{}_paid'
CHAT_MESSAGE_ITEM_KEY = '{}_{}_{}'
CHAT_MESSAGE_ITEM_USERS_KEY = '{}_{}_{}_users'

OPEN_STATUS = 'open'
WAIT_PAYMENTS_STATUS = 'wait_payments'
CLOSED_STATUS = 'closed'

DONE_BUTTON = 'done'
PAID_BUTTON = 'paid'
CLOSE_BUTTON = 'close'
RESET_BUTTON = 'reset'

redis_client = StrictRedis.from_url(REDIS_URL, charset='utf-8', decode_responses=True)

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

  result2 = result

  # return list of string
  items = []

  for line in result2:
    item = ''
    for word in line:
      item += '{} '.format(word['text'])
    items.append(item)

  return items


def subway_filter(data):
  result = []
  section = 1
  for line in data:
    line2 = []
    for word in line:
      if 'блюдо' in word['text'].lower() or 'кол-во' in word['text'].lower() \
            or 'сумма' in word['text'].lower() or 'сунна' in word['text'].lower():
        section = 2
        continue

      if 'всего' in word['text'].lower() or 'итог' in word['text'].lower():
        section = 3
        break

      line2.append(word)

    if section == 1:
      continue
    elif section == 2:
      result.append(line2)
    else:
      break
  return result

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

  raw_items = parse_ocr_output(json_data)
  content = ''

  for item in raw_items:
    content += '{}\n'.format(item)

  items = []

  inline_buttons = []
  for item in items:
    inline_buttons.append([InlineKeyboardButton('{} {}'.format(item['name'], item['total']), callback_data=item['id'])])

  message_text = start_message

  message_text += '\n\n{}'.format(content)

  bot.sendMessage(chat_id=update.message.chat_id, text=message_text,
                  parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_buttons))


def handle_receipt_stub(bot, update):
  owner_id = update.message.from_user.id
  owner_username = update.message.from_user.username
  owner_first_name = update.message.from_user.first_name
  owner_last_name = update.message.from_user.last_name

  chat_id = update.message.chat_id
  message_id = update.message.message_id + 1

  inline_buttos = [[InlineKeyboardButton('{} Я все!'.format(DONE_ICON), callback_data=DONE_BUTTON)],
                   [InlineKeyboardButton('{} Сбросить'.format(RESET_ICON), callback_data=RESET_BUTTON)],
                   [InlineKeyboardButton('{} Закрыть'.format(HAND_ICON), callback_data=CLOSE_BUTTON)]]

  redis_client.hset(USER_KEY.format(owner_id), 'un', owner_username)
  redis_client.hset(USER_KEY.format(owner_id), 'fn', owner_first_name)
  redis_client.hset(USER_KEY.format(owner_id), 'ln', owner_last_name)

  redis_client.set(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id), owner_id)
  redis_client.expire(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id), EXPIRATION)
  redis_client.set(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), 'open')
  redis_client.expire(CHAT_MESSAGE_STATUS_KEY.format(chat_id, message_id), EXPIRATION)


  for item in items:
    redis_client.sadd(CHAT_MESSAGE_ITEMS_KEY.format(chat_id, message_id), item['id'])
    redis_client.expire(CHAT_MESSAGE_ITEMS_KEY.format(chat_id, message_id), EXPIRATION)
    redis_client.hset(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item['id']), 'name', item['name'])
    redis_client.hset(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item['id']), 'price', item['total'])
    redis_client.expire(CHAT_MESSAGE_ITEM_KEY.format(chat_id, message_id, item['id']), EXPIRATION)
    inline_buttos.append([InlineKeyboardButton('{} {}'.format(item['name'], int(item['total'])), callback_data=item['id'])])

  message_text = start_message

  bot.sendMessage(chat_id=chat_id, text=message_text, parse_mode='HTML',
                  reply_markup=InlineKeyboardMarkup(inline_buttos))


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
        return

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
        bot.editMessageText(text='<b>Чек закрыт</b>', chat_id=chat_id,
                            message_id=message_id, parse_mode='HTML')
        return

    owner_id = redis_client.get(CHAT_MESSAGE_OWNER_KEY.format(chat_id, message_id))

    if button_key == CLOSE_BUTTON:
      if int(owner_id) != int(user_id):
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
    redis_client.sadd(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id), user_id)
    redis_client.expire(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id), EXPIRATION)
  elif button_key == RESET_BUTTON:
    redis_client.srem(CHAT_MESSAGE_DONE_KEY.format(chat_id, message_id), user_id)
    for item_id in item_ids:
      redis_client.srem(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, item_id), user_id)
    redis_client.srem(CHAT_MESSAGE_ITEM_USERS_KEY.format(chat_id, message_id, item_id), EXPIRATION)
  else:
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

def error_callback(bot, update, error):
  try:
    raise error
  except Exception as e:
    print(e)

dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CommandHandler('help', start))
dispatcher.add_handler(MessageHandler(Filters.photo, handle_receipt))
dispatcher.add_handler(CommandHandler('photo', handle_receipt_stub))
dispatcher.add_handler(CallbackQueryHandler(button_click))
dispatcher.add_error_handler(error_callback)

if MODE == 'webhook':
  updater.start_webhook(listen='0.0.0.0', port=PORT, url_path=TOKEN)
  updater.bot.setWebhook(URL + '/' + TOKEN)
  updater.idle()
else:
  updater.start_polling()
