.PHONY: install test lint format eval eval-live run ui

install:
	pip install -e ".[dev,ui,redis]"

test:
	pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

# Offline baseline with the same quality gate CI enforces.
eval:
	python evals/run_evals.py --min-hit-at-k 0.90 --min-keyword-recall 0.55 --min-abstention-accuracy 0.60

# Claude. Needs ANTHROPIC_API_KEY and costs real money (roughly $1 for the full set).
eval-live:
	python evals/run_evals.py --provider anthropic

run:
	uvicorn rag_service.api:create_app --factory --reload

ui:
	API_URL=http://localhost:8000 streamlit run ui/streamlit_app.py
