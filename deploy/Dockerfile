# Starter Dockerfile; add source package contents and worker process only after
# app.main:app and packaging are implemented and tested.
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
