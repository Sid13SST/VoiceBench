PYTHON ?= python3
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: setup test validate audio clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,asr]"

test:
	$(PY) -m pytest

validate:
	$(PY) -m voicebench validate scenarios/v1.jsonl

audio:
	$(PY) -m voicebench synth scenarios/v1.jsonl --out audio/v1

clean:
	rm -rf $(VENV) build dist *.egg-info src/*.egg-info .pytest_cache
