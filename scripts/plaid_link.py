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
    .venv/bin/python3 scripts/plaid_link.py
    -> open http://localhost:5055 in YOUR OWN browser, click Link,
       pick the institution, log in on Plaid's own screen (not this one).
    -> the access token prints in this terminal AND in the browser page.
       Copy it into .env as one entry of PLAID_ACCESS_TOKENS (comma-separated
       if you run this more than once for multiple institutions).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

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
  const {link_token} = await r.json();
  const handler = Plaid.create({
    token: link_token,
    onSuccess: async (public_token, metadata) => {
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
    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id="nexusai-local-user"),
        client_name="NexusAI",
        # "balance" isn't directly requestable — it's included automatically
        # once any other product is active. "auth" only surfaces accounts
        # eligible for ACH money-movement (checking/savings-style), which
        # excludes investment/retirement accounts entirely ("no eligible
        # accounts" for Fidelity 401k/HSA) — "investments" is the product
        # that actually covers those.
        products=[Products("investments")],
        country_codes=[CountryCode("US")],
        language="en",
    )
    resp = client.link_token_create(req)
    return jsonify({"link_token": resp["link_token"]})


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
