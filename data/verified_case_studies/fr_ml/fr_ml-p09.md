# Internal RAG-based Retrieval Tool (code-verified)

Project: fr_ml-p09  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p09

## Summary
This internal tool for a manufacturing client uses Python to orchestrate a retrieval-then-generation workflow powered by RAG. It leverages Hugging Face for model inference, scikit-learn for preprocessing pipelines, and serves the functionality through FastAPI. The code demonstrates a practical integration of these technologies into a single application.

## Code-verified stack
- Python: `agent.py: def retrieve_then_generate(question, store, llm):`
- RAG: `agent.py: def retrieve_then_generate(question, store, llm):`
- Hugging Face: `train.py: from transformers import AutoModelForSequenceClassification`
- scikit-learn: `train.py: from sklearn.pipeline import Pipeline`
- FastAPI: `app.py: from fastapi import FastAPI`
