-- OPSPULSE advanced analytics. Run with: python src/run_query.py sql/analytics_advanced.sql

-- A1. Monthly SLA trend with change vs previous month (CTE + LAG window function)
WITH monthly AS (
    SELECT SUBSTR(opened_at, 1, 7) AS month,
           COUNT(*) AS resolved_tickets,
           ROUND(100.0 * SUM(sla_met) / COUNT(*), 1) AS sla_met_pct
    FROM incidents
    WHERE sla_met IS NOT NULL
    GROUP BY month
)
SELECT month,
       resolved_tickets,
       sla_met_pct,
       ROUND(sla_met_pct - LAG(sla_met_pct) OVER (ORDER BY month), 1) AS change_vs_prev_month
FROM monthly
ORDER BY month;

-- A2. Running total of incidents through the year (SUM as a window function)
WITH monthly AS (
    SELECT SUBSTR(opened_at, 1, 7) AS month, COUNT(*) AS incidents
    FROM incidents
    GROUP BY month
)
SELECT month,
       incidents,
       SUM(incidents) OVER (ORDER BY month) AS running_total
FROM monthly
ORDER BY month;

-- A3. Busiest agent in each assignment group (RANK within each group)
WITH agent_load AS (
    SELECT g.group_name, i.assigned_to, COUNT(*) AS tickets
    FROM incidents i
    JOIN assignment_groups g ON g.group_id = i.group_id
    GROUP BY g.group_name, i.assigned_to
),
ranked AS (
    SELECT group_name, assigned_to, tickets,
           RANK() OVER (PARTITION BY group_name ORDER BY tickets DESC) AS rank_in_group
    FROM agent_load
)
SELECT group_name, assigned_to, tickets
FROM ranked
WHERE rank_in_group = 1
ORDER BY tickets DESC;

-- A4. The 2 slowest resolved tickets for each priority (ROW_NUMBER)
WITH ranked AS (
    SELECT incident_id, priority, category, resolution_hours,
           ROW_NUMBER() OVER (PARTITION BY priority ORDER BY resolution_hours DESC) AS rn
    FROM incidents
    WHERE resolution_hours IS NOT NULL
)
SELECT priority, incident_id, category, resolution_hours
FROM ranked
WHERE rn <= 2
ORDER BY priority, rn;

-- A5. Worst SLA performance by category and priority, with at least 20 tickets (HAVING)
SELECT category, priority,
       COUNT(*) AS resolved_tickets,
       ROUND(100.0 * SUM(sla_met) / COUNT(*), 1) AS sla_met_pct
FROM incidents
WHERE sla_met IS NOT NULL
GROUP BY category, priority
HAVING COUNT(*) >= 20
ORDER BY sla_met_pct ASC
LIMIT 5;
