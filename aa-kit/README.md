# AA kit — runs on YOUR machine, not in the cloud session

Why local: the callback needs a PUBLIC HTTPS URL, and the cloud container has no
inbound networking. The secret also never has to leave your machine.

## 1. Setup
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env        # paste ANUMATI_CLIENT_SECRET into .env
    # put the supplied jar here as fiu-crypto-lib.jar   (java -version must be 21+)

## 2. Public callback (stable hostname matters - it is provisioned once)
    python webhook_server.py &            # listens on :8080
    cloudflared tunnel --url http://localhost:8080
    # take the https URL, put it in .env as CALLBACK_PUBLIC_URL
    curl https://<host>/health            # must return ok from OUTSIDE your network

Give Anumati:
    https://<host>/aa/data-ready      (data-ready)
    https://<host>/aa/consent         (consent lifecycle)
    https://<host>/aa/callback        (works for BOTH if they want one URL)

## 3. Journey
    python run_journey.py --mobile 9999999999
    # open the printed redirectUrl, pick ACME Bank, OTP 812093
    # webhook captures data-ready -> captures/
    python run_journey.py --collect        # fetch + save RAW + decrypt

Everything lands in captures/ . Raw bodies are written BEFORE parsing, because
collection is single use and the payload is purged once collected.
