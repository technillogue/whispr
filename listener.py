import sys
import json
from flask import Flask, request, render_template

app = Flask(__name__, template_folder=".")


@app.route("/teli", methods=["POST", "GET"])
def teli() -> str:
    info = json.dumps({"sms":dict(request.form)})
    print(info, file=sys.stderr)
    print(info)
    sys.stdout.flush()
    return "ty"


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    if request.method == "POST":
        print(json.dumps(request.form))
        sys.stdout.flush()

app.run(host="0.0.0.0", port=8080)
