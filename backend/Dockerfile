FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 모든 백엔드 포트 노출
EXPOSE 50052 50053 50054 50055 50056

# 환경변수로 실행할 백엔드 서비스 결정
ENV BACKEND_TYPE=all

# 실행 스크립트
COPY backend/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]