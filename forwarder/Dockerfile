FROM python:3.12-slim

RUN pip install uv --no-cache-dir

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system .

CMD ["python", "-m", "forwarder"]
