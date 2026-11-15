"""One-time local tool to link an institution via Plaid Link and print the
resulting access token.

Run this once PER INSTITUTION (once for Fidelity, once for Webull, etc).
Nothing here ever sees your bank password — you authorize each institution
inside Plaid's own hosted widget, in your own browser. This script only
handles the two server-side steps Plaid Link needs a backend for:
  1. Create a link_token (tells Plaid Link what your app is / what to show)
  2. Exchange the public_token Link hands back for a permanent access_token

Setup:
    .venv/bin/pip install plaid-python flask
    export PLAID_CLIENT_ID=...
    export PLAID_SECRET=...        # your Trial/Development/Production secret
    export PLAID_ENV=production    # or development/sandbox

Run:
    .venv/bin/python3 scripts/plaid_link.py                          # new institution (investments)
    .venv/bin/python3 scripts/plaid_link.py --products transactions   # new bank / credit card
    .venv/bin/python3 scripts/plaid_link.py --update 1 --products transactions
        # add transactions consent to the 2nd token in PLAID_ACCESS_TOKENS
        # (0-based); no new token is issued, nothing to paste into .env.
    -> open http://localhost:5055 in YOUR OWN browser, click Link,
       pick the institution, log in on Plaid's own screen (not this one).
    -> the access token prints in this terminal AND in the browser page.
       Copy it into .env as one entry of PLAID_ACCESS_TOKENS (comma-separated
       if you run this more than once for multiple institutions).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import argparse

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv(os.path.join(ROOT, ".env"))  # before plaid_sync reads the environment

import plaid_sync  # noqa: E402

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "").strip()
PLAID_SECRET = os.getenv("PLAID_SECRET", "").strip()
PLAID_ENV = os.getenv("PLAID_ENV", "production").strip()

if not (PLAID_CLIENT_ID and PLAID_SECRET):
    print("Set PLAID_CLIENT_ID and PLAID_SECRET first (from your Plaid dashboard).")
    sys.exit(1)

try:
    from plaid.api import plaid_api
    from plaid import Configuration, ApiClient
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.products import Products
    from plaid.model.country_code import CountryCode
    from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
except ImportError:
    print("plaid-python not installed. Run: .venv/bin/pip install plaid-python")
    sys.exit(1)

_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}
_cfg = Configuration(host=_HOSTS.get(PLAID_ENV, _HOSTS["production"]),
                      api_key={"clientId": PLAID_CLIENT_ID, "secret": PLAID_SECRET})
client = plaid_api.PlaidApi(ApiClient(_cfg))

_ap = argparse.ArgumentParser()
_ap.add_argument("--update", type=int, default=None, help="0-based index of an existing Item to update")
_ap.add_argument("--products", default="investments", help="comma-separated: transactions,investments,liabilities")
ARGS = _ap.parse_args()
try:
    LINK_KWARGS = plaid_sync.link_request_kwargs(
        ARGS.update, [p.strip() for p in ARGS.products.split(",") if p.strip()],
        plaid_sync.PLAID_ACCESS_TOKENS)
except ValueError as _e:
    print(f"Bad arguments: {_e}")
    sys.exit(1)
UPDATE_MODE = ARGS.update is not None

app = Flask(__name__)

PAGE = """<!doctype html><html><body style="font-family:sans-serif;max-width:480px;margin:60px auto;">
<h2>NexusAI &mdash; Plaid Link (local, one-time setup)</h2>
<p>Click below, then authorize <b>one institution</b> in Plaid's own popup.
Nothing you type there is seen by this app or by Claude.</p>
<button id="btn" style="padding:10px 20px;font-size:16px;">Link an account</button>
<pre id="out" style="background:#f4f4f4;padding:12px;white-space:pre-wrap;"></pre>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
async function start() {
  const r = await fetch('/create_link_token', {method: 'POST'});
  const {link_token, update_mode} = await r.json();
  const handler = Plaid.create({
    token: link_token,
    onSuccess: async (public_token, metadata) => {
      if (update_mode) {
        document.getElementById('out').textContent =
          'Updated. This institution now shares the extra data; the existing access token is unchanged.';
        return;
      }
      const ex = await fetch('/exchange', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({public_token, institution: metadata.institution?.name || ''})
      });
      const data = await ex.json();
      document.getElementById('out').textContent =
        'Institution: ' + data.institution + '\\n' +
        'Access token (copy this into .env):\\n' + data.access_token;
    },
    onExit: (err) => { if (err) document.getElementById('out').textContent = 'Exited: ' + JSON.stringify(err); },
  });
  handler.open();
}
document.getElementById('btn').addEventListener('click', start);
</script>
</body></html>"""


@app.route("/")
def index():
    return PAGE


@app.route("/create_link_token", methods=["POST"])
def create_link_token():
    kw = dict(LINK_KWARGS)
    if "products" in kw:
        kw["products"] = [Products(p) for p in kw["products"]]
    if "additional_consented_products" in kw:
        kw["additional_consented_products"] = [Products(p) for p in kw["additional_consented_products"]]
    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id="nexusai-local-user"),
        client_name="NexusAI",
        # "balance" isn't directly requestable — it's included automatically
        # once any other product is active. "auth" only surfaces accounts
        # eligible for ACH money-movement, which excludes investment/retirement
        # accounts — "investments" covers those; "transactions" covers
        # checking/credit-card activity for the cash-flow view.
        country_codes=[CountryCode("US")],
        language="en",
        **kw,
    )
    resp = client.link_token_create(req)
    return jsonify({"link_token": resp["link_token"], "update_mode": UPDATE_MODE})


@app.route("/exchange", methods=["POST"])
def exchange():
    body = request.get_json(force=True)
    resp = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=body["public_token"])
    )
    access_token = resp["access_token"]
    institution = body.get("institution", "")
    print(f"\n=== Linked: {institution} ===")
    print(f"Access token: {access_token}")
    print("Add it to .env as PLAID_ACCESS_TOKENS (comma-separated if linking more than one).\n")
    return jsonify({"access_token": access_token, "institution": institution})


if __name__ == "__main__":
    print(f"Plaid env: {PLAID_ENV}")
    print("Open http://localhost:5055 in your own browser to link an institution.")
    app.run(port=5055, debug=False)
