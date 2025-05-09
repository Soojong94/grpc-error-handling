#!/bin/bash

# 도커 이미지 빌드 (0509 태그)
echo "빌드 중: DB 서비스 (0509)"
docker build -t soojongkim/grpc-error-handling:db-0509 -f db/Dockerfile .

echo "빌드 중: Backend 서비스 (0509)"
docker build -t soojongkim/grpc-error-handling:backend-0509 -f backend/Dockerfile .

echo "빌드 중: BFF 서비스 (0509)"
docker build -t soojongkim/grpc-error-handling:bff-0509 -f bff/Dockerfile .

echo "빌드 중: Frontend 서비스 (0509)"
docker build -t soojongkim/grpc-error-handling:frontend-0509 -f front/Dockerfile .

# 백엔드 패턴별 태그 생성 (0509)
echo "백엔드 패턴별 태그 생성 중 (0509)..."
docker tag soojongkim/grpc-error-handling:backend-0509 soojongkim/grpc-error-handling:backend-no-pattern-0509
docker tag soojongkim/grpc-error-handling:backend-0509 soojongkim/grpc-error-handling:backend-circuit-breaker-0509
docker tag soojongkim/grpc-error-handling:backend-0509 soojongkim/grpc-error-handling:backend-deadline-0509
docker tag soojongkim/grpc-error-handling:backend-0509 soojongkim/grpc-error-handling:backend-backpressure-0509
docker tag soojongkim/grpc-error-handling:backend-0509 soojongkim/grpc-error-handling:backend-all-0509

# Docker Hub에 이미지 푸시 (0509 태그)
echo "Docker Hub에 이미지 푸시 중 (0509)..."
docker push soojongkim/grpc-error-handling:db-0509
docker push soojongkim/grpc-error-handling:backend-0509
docker push soojongkim/grpc-error-handling:bff-0509
docker push soojongkim/grpc-error-handling:frontend-0509

# 백엔드 패턴별 이미지 푸시 (0509 태그)
docker push soojongkim/grpc-error-handling:backend-no-pattern-0509
docker push soojongkim/grpc-error-handling:backend-circuit-breaker-0509
docker push soojongkim/grpc-error-handling:backend-deadline-0509
docker push soojongkim/grpc-error-handling:backend-backpressure-0509
docker push soojongkim/grpc-error-handling:backend-all-0509

echo "모든 이미지 업데이트 완료! (0509 태그)"