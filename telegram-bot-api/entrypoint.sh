#!/bin/sh
# TELEGRAM_API_ID and TELEGRAM_API_HASH are read by the binary itself,
# TELEGRAM_LOCAL=1 enables --local.
set -e
exec /usr/local/bin/telegram-bot-api \
	--http-port=8081 \
	--dir=/data \
	--temp-dir=/data/temp \
	${TELEGRAM_LOCAL:+--local} \
	"$@"
