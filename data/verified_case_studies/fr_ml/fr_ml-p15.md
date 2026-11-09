# Education Data Classification Tool (code-verified)

Project: fr_ml-p15  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p15

## Summary
The project implements an internal tool for an education client that processes textual data using a PyTorch-based model from Hugging Face. The core logic is written in Python and leverages the OpenAI API for supplementary features. A Dockerfile is provided for easy deployment, and the application can be launched locally with a simple make command.

## Code-verified stack
- Python: `app.py: def main() -> None:`
- PyTorch: `train.py: import torch`
- Hugging Face: `train.py: from transformers import AutoModelForSequenceClassification`
- OpenAI API: `app.py: from openai import OpenAI`
- Docker: `Dockerfile: FROM python:3.12-slim`
