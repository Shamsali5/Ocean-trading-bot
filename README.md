# Ocean Telegram Runner

Python CLI runner that fetches Binance Futures OHLCV data, sends it to the OpenAI Responses API using the Ocean x Natural Chanlun framework, saves the analysis locally, and posts the result to Telegram.

## Setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `python3 -m venv` fails on Ubuntu with `ensurepip is not available`, install the venv package first:

```sh
sudo apt-get update
sudo apt-get install -y python3.12-venv
```

## Configuration

Required environment variables:

```sh
export OPENAI_API_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

Useful optional variables:

```sh
export OCEAN_OPENAI_MODEL="gpt-5.4"
export OCEAN_REASONING_EFFORT="high"
export OCEAN_SYMBOLS="BTCUSDT"
export OCEAN_TELEGRAM_MODE="compact"
export OCEAN_RUN_EVERY_HALF_HOUR="0"
```

## Run

Run once:

```sh
. .venv/bin/activate
OCEAN_RUN_EVERY_HALF_HOUR=0 python ocean_telegram_runner.py
```

Run continuously on the half-hour schedule:

```sh
. .venv/bin/activate
python ocean_telegram_runner.py
```

The runner writes raw OHLCV data to `ohlcv_data/` and analyses to `analysis_results/`.
