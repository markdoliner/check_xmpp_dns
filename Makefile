.DEFAULT_GOAL:=check

.PHONY: install-deps
install-deps:
	poetry install --no-root --with=dev

.PHONY: check
check:
	poetry run ruff format check_xmpp_dns.py
	poetry run ruff check --fix check_xmpp_dns.py
	poetry run mypy check_xmpp_dns.py

.PHONY: run-local
run-local:
	poetry run uvicorn --factory --no-server-header --reload check_xmpp_dns:application

.PHONY: docker
docker:
	docker build --tag=check-xmpp-dns .

.PHONY: run-docker
run-docker: docker
	docker run --name check-xmpp-dns --publish=127.0.0.1:8000:8000/tcp --rm check-xmpp-dns
