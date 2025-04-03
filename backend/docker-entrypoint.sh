#!/bin/bash

case "$BACKEND_TYPE" in
  "no_pattern")
    echo "Starting Backend with No Pattern"
    exec python backend/backend_service_no_pattern.py
    ;;
  "circuit_breaker")
    echo "Starting Backend with Circuit Breaker Pattern"
    exec python backend/backend_service_circuit_breaker.py
    ;;
  "deadline")
    echo "Starting Backend with Deadline Pattern"
    exec python backend/backend_service_deadline.py
    ;;
  "backpressure")
    echo "Starting Backend with Backpressure Pattern"
    exec python backend/backend_service_backpressure.py
    ;;
  "all")
    echo "Starting Backend with All Patterns"
    exec python backend/backend_service_all.py
    ;;
  *)
    echo "Unknown backend type: $BACKEND_TYPE, using default (all)"
    exec python backend/backend_service_all.py
    ;;
esac