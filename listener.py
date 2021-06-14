import sys
import json
import logging
from flask import Flask, request, render_template
import json2html


app = Flask(__name__, template_folder=".")


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        print(json.dumps(request.form))
        sys.stdout.flush()
    return render_template("form.html")

try:
    log = json.load(open("dummy_log.json"))
except:
    log = []

@app.route("/hook_dest", methods=["POST"])
def dest():
    log.append(dict(request.form))
    return "received"

@app.route("/log")
def view_log():
    return "<!DOCTYPE html>" + json2html.json2html.convert(log)

try:
    app.run(host="0.0.0.0", port=8080)
finally:
    json.dump(open("dummy_log.json", "w"), log)
