FROM python:3.10-alpine

WORKDIR /app

COPY main.py .

RUN adduser -D appuser
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost:5000/health || exit 1

CMD ["python", "main.py"]
