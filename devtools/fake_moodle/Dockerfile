FROM python:3.12-slim
WORKDIR /app
COPY devtools/fake_moodle /app/fake_moodle
ENV PYTHONUNBUFFERED=1
EXPOSE 8090
CMD ["python", "-m", "fake_moodle.app", "--port", "8090"]
