.DEFAULT_GOAL:=check

.PHONY: sort-imports
sort-imports:
	isort check_xmpp_dns.py

.PHONY: check
check:
	@if ! isort --check-only check_xmpp_dns.py; then \
		>&2 echo "\nRun 'make sort-imports' to fix.\n"; \
		exit 1; \
	fi
