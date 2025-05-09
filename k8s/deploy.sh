#!/bin/bash

# 미니쿠베 시작 (이미 실행 중이라면 생략 가능)
minikube start

# 네임스페이스 생성
kubectl apply -f namespace.yaml

# ConfigMap 배포
kubectl apply -f configmap.yaml

# 이미지 빌드 (미니쿠베 환경 내에서)
eval $(minikube docker-env)
docker build -t grpc-error-handling-db:latest -f db/Dockerfile .
docker build -t grpc-error-handling-backend:latest -f backend/Dockerfile .
docker build -t grpc-error-handling-bff:latest -f bff/Dockerfile .
docker build -t grpc-error-handling-frontend:latest -f front/Dockerfile .

# 서비스 배포
kubectl apply -f db-service.yaml
kubectl apply -f backend-service.yaml
kubectl apply -f bff-service.yaml
kubectl apply -f frontend.yaml

# Ingress 컨트롤러 활성화 (필요한 경우)
minikube addons enable ingress

# 배포 상태 확인
kubectl get pods -n grpc-error-handling

# 프론트엔드 URL 출력
echo "프론트엔드 접속 URL (잠시 후 사용 가능):"
minikube service frontend -n grpc-error-handling --url