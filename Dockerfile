FROM python:3.12-slim

WORKDIR /app

COPY pip/requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src

CMD ["python", "src/main.py"]
