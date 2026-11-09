# Healthcare ML API Service (code-verified)

Project: fr_ml-p04  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p04

## Summary
This internal tool for a healthcare client combines a FastAPI server written in Python with a PyTorch training pipeline. The application uses MLOps practices by logging experiments with mlflow, and it is containerized with Docker for easy deployment. The project demonstrates Python, FastAPI, PyTorch, MLOps, and Docker skills.

## Code-verified stack
- Python: `app.py: from fastapi import FastAPI`
- PyTorch: `train.py: import torch`
- FastAPI: `app.py: from fastapi import FastAPI`
- MLOps: `train.py: import mlflow`
- Docker: `Dockerfile: FROM python:3.12-slim`
