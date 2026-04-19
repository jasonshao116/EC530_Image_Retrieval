PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTHONPATH := src
EVENT_EXAMPLES := examples/image.uploaded.json examples/image.indexed.json examples/retrieval.requested.json examples/retrieval.completed.json
DEMO_QUERY ?= red brick campus building
TOP_K ?= 3
API_HOST ?= 127.0.0.1
API_PORT ?= 8000

.PHONY: all install validate demo generate test openapi api clean

all: validate test openapi

install:
	$(PIP) install -r requirements.txt

validate:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m image_retrieval.demo validate $(EVENT_EXAMPLES)

demo:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m image_retrieval.demo demo --query "$(DEMO_QUERY)" --top-k $(TOP_K)

generate:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m image_retrieval.demo generate --images 3 --retrievals 2 --top-k $(TOP_K) --seed 530 --format json

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -v

openapi:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -c "from image_retrieval.api import app; print(app.title); print(len(app.openapi()['paths']))"

api:
	PYTHONPATH=$(PYTHONPATH) uvicorn image_retrieval.api:app --host $(API_HOST) --port $(API_PORT) --reload

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".coverage" \) -delete
