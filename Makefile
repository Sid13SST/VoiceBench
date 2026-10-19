PYTHON ?= python3
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: setup setup-locked test validate audio audio-check bench run clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,asr]"

# Same package versions as the committed day 5 runs (Python 3.13).
setup-locked:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements-lock.txt
	$(PY) -m pip install --no-deps -e .

test:
	$(PY) -m pytest

validate:
	$(PY) -m voicebench validate scenarios/v1.jsonl

audio:
	$(PY) -m voicebench synth scenarios/v1.jsonl --out audio/v1

audio-check:
	$(PY) -m voicebench synth scenarios/v1.jsonl --out audio/v1 --check

# Full benchmark with the baseline ASR. Downloads Whisper "small" from
# huggingface.co on first use. MODEL=/path/to/ct2-dir to use local weights.
MODEL ?= small
POLICY ?= auto
bench:
	$(PY) -m voicebench run --model $(MODEL) --language-policy $(POLICY) --out results

HOST ?= 127.0.0.1
PORT ?= 8000
run:
	$(PY) -m voicebench dashboard --host $(HOST) --port $(PORT)

clean:
	rm -rf $(VENV) build dist *.egg-info src/*.egg-info .pytest_cache
