[@SplitWithBot](https://t.me/splitwithbot)
==========================================

<img align="right" src="http://is5.mzstatic.com/image/thumb/Purple122/v4/e5/f7/6f/e5f76f46-c4e3-f43a-f7b6-a78877f63a9b/source/175x175bb.png">
Telegram bot for splitting receipts between participants in your chats

https://t.me/splitwithbot

## Deployment
 
### Bot configuration 
 
| environment variable  | notes                   |
|-----------------------|-------------------------|
| MODE                  | `webhook` or `polling`  |
| REDIS_URL             | connection url to redis |
| TOKEN                 | telegram bot token      |
| URL                   | heroku app url          |
| AWS_ACCESS_KEY_ID     | aws access key id       |
| AWS_SECRET_ACCESS_KEY | aws secret access key   |
| AWS_S3_BUCKET         | aws s3 bucket name      |
| AWS_REGION            | aws s3 region           |
| OCR_API_TOKEN         | ocr.space token         |
| EXPIRATION            | ttl for redis hashes    |

### Components

* Telegram Bot with Redis on [Heroku](https://heroku.com)

## How we store information in redis
| hash key                                 | hash value                                      |
|------------------------------------------|-------------------------------------------------|
| `user_<user_id>`                         | dictionary with fields `un`, `fn`, `ln`         |
| `<chat_id>_<message_id>_owner`           | owner id                                        |
| `<chat_id>_<message_id>_status`          | check status `open`, `wait_payments`, `closed`  |
| `<chat_id>_<message_id>_items`           | set with `item_id` of items                     |
| `<chat_id>_<message_id>_done>`           | set with `user_id` of users who clicked `done`  |
| `<chat_id>_<message_id>_paid`            | set with `user_id` of users who clicked `paid`  |
| `<chat_id>_<message_id>_<item_id>`       | dictionary with fields `name`, `price`          |
| `<chat_id>_<message_id>_<item_id>_users` | set with `user_id` of users who clicked on item |
