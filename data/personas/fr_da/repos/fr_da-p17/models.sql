SELECT user_id, SUM(amount) OVER (PARTITION BY user_id) FROM orders;
{{ config(materialized='table') }}
USE WAREHOUSE analytics_wh;
