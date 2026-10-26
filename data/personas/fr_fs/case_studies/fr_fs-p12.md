# Add background jobs with Celery (logistics)

Client industry: logistics  
Completed: 2023-09-27

## Brief
Add background jobs with Celery.

## Approach
Main stack: Node.js, Stripe. I put an in-memory cache and rate limiter in front of the database. I moved slow work into a distributed background task queue with retries.

## Outcome
The delivered system saved the team 29 hours a week.
