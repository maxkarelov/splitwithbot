CREATE TABLE feedback (
  user_id BIGINT NOT NULL,
  username VARCHAR,
  first_name VARCHAR,
  last_name VARCHAR,
  chat_id BIGINT NOT NULL,
  message_id BIGINT NOT NULL,
  text TEXT,
  date TIMESTAMP
);

CREATE TABLE report (
  user_id BIGINT NOT NULL,
  username VARCHAR,
  first_name VARCHAR,
  last_name VARCHAR,
  chat_id BIGINT NOT NULL,
  message_id BIGINT NOT NULL,
  url VARCHAR,
  date TIMESTAMP
);
