# Legal Client Internal Tool (code-verified)

Project: fr_ml-p06  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p06

## Summary
An internal tool for a legal client that integrates a retrieval-augmented generation agent built in Python. It leverages PyTorch for model training, FastAPI to expose the service, and Docker to containerise the deployment.

## Code-verified stack
- Python: `agent.py: def retrieve_then_generate(question, store, llm):`
- PyTorch: `train.py: import torch`
- RAG: `agent.py: def retrieve_then_generate(question, store, llm):`
- FastAPI: `app.py: from fastapi import FastAPI`
- Docker: `Dockerfile: FROM python:3.12-slim`
