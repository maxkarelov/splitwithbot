CREATE TABLE feedback (
  user_id INTEGER NOT NULL,
  username VARCHAR,
  first_name VARCHAR,
  last_name VARCHAR,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  text TEXT,
  date TIMESTAMP
);

CREATE TABLE report (
  user_id INTEGER NOT NULL,
  username VARCHAR,
  first_name VARCHAR,
  last_name VARCHAR,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  url VARCHAR,
  date TIMESTAMP
);
