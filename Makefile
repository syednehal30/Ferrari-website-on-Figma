.PHONY: install run test
install:
	bash scripts/install.sh
run:
	bash scripts/run.sh
test:
	.venv/bin/python -m unittest discover -s tests -v
