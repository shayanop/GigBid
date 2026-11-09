# Internal E-commerce RAG Tool (code-verified)

Project: fr_ml-p11  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_ml/repos/fr_ml-p11

## Summary
This internal tool for an e-commerce client combines retrieval-augmented generation (RAG) with a FastAPI interface. The Python backend implements a retrieve-then-generate agent that pulls context from a store and feeds it to a language model. Training of the model uses Hugging Face Transformers and scikit-learn pipelines. The service is exposed via FastAPI for local development.

## Code-verified stack
- Python: `agent.py: def retrieve_then_generate(question, store, llm):`
- RAG: `agent.py: def retrieve_then_generate(question, store, llm):`
- Hugging Face: `train.py: from transformers import AutoModelForSequenceClassification`
- scikit-learn: `train.py: from sklearn.pipeline import Pipeline`
- FastAPI: `app.py: from fastapi import FastAPI`
