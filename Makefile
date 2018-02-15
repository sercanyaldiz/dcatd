.PHONY: .test_requirements test cov install dist upload example clean

RM = rm -rf
PYTHON = python3


# ┏━━━━┓
# ┃ DB ┃
# ┗━━━━┛

schema schema_jenkins schema_acc:
	$(MAKE) -C alembic $@

dbwait:
	@echo Giving DB 5 seconds to come up
	@sleep 5

# ┏━━━━━━━━━┓
# ┃ Testing ┃
# ┗━━━━━━━━━┛

PYTEST = $(PYTHON) setup.py test
PYTEST_COV_OPTS ?= --cov=src --cov-report=term --no-cov-on-fail


test: cleanpy schema
	$(PYTEST)


waittest: cleanpy dbwait schema
	$(PYTEST)


cov: cleanpy schema
	$(PYTEST) $(PYTEST_COV_OPTS)


testdep:
	pip3 install --quiet --upgrade --upgrade-strategy eager -e .[test] && echo 'OK' || echo 'FAILED'


testclean: cleanpy
	@$(RM) .cache .coverage


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃ Installing, building, running ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

install: cleanpy
	@echo -n 'Installing... '
	@pip3 install --quiet --upgrade --upgrade-strategy eager -e . && echo 'OK' || echo 'FAILED'

dist: cleanpy
	$(PYTHON) setup.py sdist

upload: cleanpy
	$(PYTHON) setup.py sdist upload

example: cleanpy
	@echo Starting example server:
	@docker-compose up api


# ┏━━━━━━━━━━━━━┓
# ┃ Cleaning up ┃
# ┗━━━━━━━━━━━━━┛

cleanpy:
	@echo Removing pyc and pyo files
	@find . -type f -name '*.py[co]' -exec rm {} \;

clean:
	@# From running pytest:
	$(RM) .coverage .cache

	@# From `pip3 install -e .`:
	-pip3 uninstall -y datacatalog-core && $(RM) src/datacatalog_core.egg-info

	@# From `setup.py sdist`:
	$(RM) dist
