{{ config(materialized='table') }}
SELECT user_id, SUM(amount) OVER (PARTITION BY user_id) FROM orders;
USE WAREHOUSE analytics_wh;
