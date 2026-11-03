# Python uses the application's image, independent of the Forgejo runner OS.
FROM python:3.13-slim AS check
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY bot/requirements.txt bot/requirements.txt
RUN python -c 'import subprocess,sys,tomllib; d=tomllib.load(open("backend/pyproject.toml","rb")); subprocess.check_call([sys.executable,"-m","pip","install",*d["project"]["dependencies"]])' \
    && python -m pip install --no-cache-dir -r bot/requirements.txt
COPY backend/ backend/
COPY bot/ bot/
COPY tests/ tests/
RUN python -m unittest discover -s tests -v && python -m compileall -q backend bot
