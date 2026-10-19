#!/usr/bin/env python3
"""Live smoke test: real, billed requests through every skill script.

Usage:
  EMPIRIOLABS_API_KEY=... python tests/live_smoke.py --out ./smoke-output [--video] [--budget 0.15]

Steps (each runs the real script as a subprocess, exactly as an agent would):
  1. models.py lists image models (free, public catalog)
  2. image.py makes one image with the default model
  3. speech.py speaks one short sentence with the default model
  4. transcribe.py transcribes a short public sample with the default model
  5. video.py (only with --video) makes a 1-second 480p clip, if its listed price is under $0.10

Before each billed step the listed catalog price is checked against the remaining budget.
Afterwards each step is matched to its own usage event from GET /v1/account/usage (by output
URL, or by model and time window for transcription), so other traffic on the account is not
counted. Every output is scanned to make sure the API key never appears.
Exit codes: 0 all steps passed, 1 a step failed, 2 could not run.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

import empiriolabs_api as api  # noqa: E402

SAMPLE_AUDIO = "https://media.empiriolabs.ai/assets/samples/ocean-sample.wav"
VIDEO_MODEL = "hunyuan-video-1-5"


def script(skill, name):
    return os.path.join(ROOT, "skills", skill, "scripts", name)


def run(label, cmd, key):
    started = time.time()
    proc = subprocess.run([sys.executable, "-B"] + cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=3600)
    ended = time.time()
    leaked = bool(key) and (key in proc.stdout or key in proc.stderr)
    print("--- " + label + " (exit " + str(proc.returncode) + ", " + str(round(ended - started, 1)) + "s)")
    if proc.stderr.strip():
        print("    stderr: " + proc.stderr.strip().replace("\n", "\n            ")[:1500])
    if leaked:
        print("    FAIL: the API key appeared in the output")
    return proc, (proc.returncode == 0 and not leaked), started, ended


def summary_of(proc, ok):
    if not ok:
        return {}
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {}


def per_unit_price(model, label_hint=None):
    """First dollar amount in the model's price rows (optionally a row whose label contains label_hint)."""
    for row in model.get("pricing_rows") or []:
        if label_hint and label_hint.lower() not in str(row.get("label", "")).lower():
            continue
        match = re.search(r"\$([0-9]*\.?[0-9]+)", str(row.get("value", "")))
        if match:
            return float(match.group(1)), str(row.get("spec", ""))
    return None, ""


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(text):
    """ISO timestamps with any number of fractional digits (Python 3.8 accepts only 3 or 6)."""
    text = str(text or "").replace("Z", "+00:00")
    text = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], text)
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def basename(url):
    return str(url).split("?")[0].rsplit("/", 1)[-1]


def attribute_spend(steps, wait=180):
    """Match each billed step to its own usage event.

    A step that returned hosted files is matched by output URL. A step without files
    (transcription) is matched by model, choosing the event closest to the step's end
    inside its own time window.
    """
    deadline = time.time() + wait
    found = {}
    while True:
        for index, step in enumerate(steps):
            if index in found:
                continue
            query = urllib.parse.urlencode({"model": step["model"], "from": iso(step["start"] - 5),
                                            "to": iso(step["end"] + 120), "limit": 50})
            events = api.get_json("/account/usage?" + query).get("data") or []
            names = {basename(u) for u in step["urls"]}
            if names:
                matches = [e for e in events if names & {basename(u) for u in e.get("output_urls") or []}]
            else:
                timed = [e for e in events if parse_ts(e.get("created_at")) is not None]
                matches = sorted(timed, key=lambda e: abs(parse_ts(e.get("created_at")) - step["end"]))
            if matches:
                found[index] = (matches[0], "output url" if names else "time window")
        if len(found) == len(steps) or time.time() > deadline:
            return found
        time.sleep(10)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="Directory for the generated files.")
    parser.add_argument("--video", action="store_true", help="Also run one short video if it costs under $0.10.")
    parser.add_argument("--budget", type=float, default=0.15, help="Upper bound on listed prices for the run (USD).")
    args = parser.parse_args(argv)
    key = (os.environ.get(api.KEY_ENV) or "").strip()
    if not key:
        print("EMPIRIOLABS_API_KEY is not set.", file=sys.stderr)
        return 2
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    catalog = list(api.list_models())
    by_id = {m["id"]: m for m in catalog}
    remaining = args.budget
    results = {}
    billed = []

    proc, ok, _start, _end = run("models: image category",
                                 [script("empiriolabs-models", "models.py"), "--category", "image", "--json"], key)
    try:
        results["models"] = ok and len(json.loads(proc.stdout)) > 0
    except ValueError:
        results["models"] = False

    image_model = api.pick_default(catalog, "POST /v1/images/generations", "image")
    price, _spec = per_unit_price(image_model)
    print("image default " + image_model["id"] + " listed at $" + str(price) + " per image")
    if price is not None and price <= remaining:
        proc, ok, start, end = run("image", [script("empiriolabs-image", "image.py"),
                                             "a small red paper boat on a calm blue pond, minimal flat illustration",
                                             "--out", os.path.join(out, "image") + os.sep], key)
        summary = summary_of(proc, ok)
        files = summary.get("files") or []
        results["image"] = ok and bool(files) and os.path.getsize(files[0]) > 1000
        billed.append({"label": "image", "model": summary.get("model") or image_model["id"],
                       "start": start, "end": end, "urls": summary.get("urls") or []})
        remaining -= price
        print("    " + json.dumps(summary))
    else:
        results["image"] = False
        print("image skipped: listed price does not fit the budget")

    tts_model = api.pick_default(catalog, "POST /v1/audio/speech", "audio")
    proc, ok, start, end = run("speech (" + tts_model["id"] + ")",
                               [script("empiriolabs-speech", "speech.py"), "EmpirioLabs AI skills smoke test.",
                                "--out", os.path.join(out, "speech.mp3")], key)
    summary = summary_of(proc, ok)
    files = summary.get("files") or []
    results["speech"] = ok and bool(files) and os.path.getsize(files[0]) > 1000
    billed.append({"label": "speech", "model": summary.get("model") or tts_model["id"],
                   "start": start, "end": end, "urls": summary.get("urls") or []})
    print("    " + json.dumps(summary))

    stt_model = api.pick_default(catalog, "POST /v1/audio/transcriptions", "transcription")
    proc, ok, start, end = run("transcribe (" + stt_model["id"] + ")",
                               [script("empiriolabs-transcribe", "transcribe.py"), SAMPLE_AUDIO,
                                "--out", os.path.join(out, "transcript.json")], key)
    summary = summary_of(proc, ok)
    results["transcribe"] = ok and bool(summary.get("file")) and os.path.isfile(summary["file"])
    billed.append({"label": "transcribe", "model": summary.get("model") or stt_model["id"],
                   "start": start, "end": end, "urls": []})
    print("    " + json.dumps(summary))
    if results["transcribe"]:
        with open(summary["file"], encoding="utf-8") as handle:
            print("    transcript: " + json.dumps(json.load(handle).get("text"))[:300])

    if args.video:
        price, spec = per_unit_price(by_id.get(VIDEO_MODEL) or {}, "480p")
        estimate = price if price is not None and "second" in spec else None
        print("video " + VIDEO_MODEL + " 480p listed at $" + str(price) + " " + spec
              + ", estimate for 1 second: $" + str(estimate))
        if estimate is not None and estimate < 0.10 and estimate <= remaining:
            proc, ok, start, end = run("video", [script("empiriolabs-video", "video.py"),
                                                 "gentle ocean waves rolling onto a sandy beach at sunset",
                                                 "--model", VIDEO_MODEL, "--resolution", "480p", "--duration", "1",
                                                 "--out", os.path.join(out, "video.mp4"), "--timeout", "1500"], key)
            summary = summary_of(proc, ok)
            files = summary.get("files") or []
            results["video"] = ok and bool(files) and os.path.getsize(files[0]) > 1000
            billed.append({"label": "video", "model": VIDEO_MODEL, "start": start, "end": end,
                           "urls": summary.get("urls") or []})
            print("    " + json.dumps(summary))
        else:
            print("video skipped: a run would not cost under $0.10 within the budget")

    found = attribute_spend(billed)
    total = 0.0
    print("--- spend for this run (matched usage events)")
    for index, step in enumerate(billed):
        if index not in found:
            print("    " + step["label"].ljust(11) + " " + step["model"].ljust(26) + " no usage event found yet")
            continue
        event, how = found[index]
        amount = float(((event.get("cost") or {}).get("amount")) or 0)
        total += amount
        print("    " + step["label"].ljust(11) + " " + step["model"].ljust(26) + " $" + format(amount, ".6f")
              + "  (matched by " + how + ")")
    print("    total $" + format(total, ".6f") + " (budget $" + format(args.budget, ".2f") + ")")
    print("--- results: " + json.dumps(results))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
