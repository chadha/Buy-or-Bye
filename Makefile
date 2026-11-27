.PHONY: dev check demo data
dev:
	uvicorn app.main:app --reload --port 8000
check:
	ruff check . && ruff format --check . && mypy && pytest -q
demo:
	python -m app.demo
data:
	python scripts/make_demo_data.py
