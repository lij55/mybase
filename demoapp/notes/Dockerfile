FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_KIND=notes PORT=8080
COPY common/server.py /app/server.py
COPY common/common.js common/style.css /app/static/
COPY notes/static/index.html /app/static/index.html
COPY common/items.js /app/static/app.js
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/server.py"]
