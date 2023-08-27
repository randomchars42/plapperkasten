.PHONY: run setup build upload

run:
	pipenv run plapperkasten

setup:
	pipenv install --dev

build:
dist:
	rm -rf dist
	pipenv run python -m build

upload: dist
	pipenv run python -m twine upload dist/*
	rm -rf dist
