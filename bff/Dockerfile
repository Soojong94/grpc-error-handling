FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 50051

# 환경변수 기본값 설정
ENV CIRCUIT_BREAKER_FAIL_THRESHOLD=3
ENV CIRCUIT_BREAKER_RESET_TIMEOUT=10
ENV DEADLINE_TIMEOUT=1.0
ENV BACKPRESSURE_WINDOW=5
ENV BACKPRESSURE_MAX_REQUESTS=30
ENV BACKPRESSURE_MAX_CONCURRENCY=8

# 헬스체크 엔드포인트 추가를 위한 패키지 설정
RUN pip install --no-cache-dir grpcio-health-checking

CMD ["python", "bff/bff_service.py"]