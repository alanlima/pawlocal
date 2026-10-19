FROM python:3.12-slim

WORKDIR /app
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/pawlocal ./pawlocal
COPY backend/data ./data
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "pawlocal.main:app", "--host", "0.0.0.0", "--port", "8000"]
