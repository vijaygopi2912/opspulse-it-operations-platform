-- OPSPULSE basic analytics. Run with: python src/run_query.py sql/analytics_basic.sql

-- Q1. How many incidents per priority?
SELECT priority, COUNT(*) AS incidents
FROM incidents
GROUP BY priority
ORDER BY priority;

-- Q2. SLA compliance per priority (valid resolved tickets only)
SELECT i.priority,
       p.sla_target_hours,
       COUNT(*) AS resolved_tickets,
       ROUND(100.0 * SUM(i.sla_met) / COUNT(*), 1) AS sla_met_pct
FROM incidents i
JOIN priorities p ON p.priority = i.priority
WHERE i.sla_met IS NOT NULL
GROUP BY i.priority, p.sla_target_hours
ORDER BY i.priority;

-- Q3. Workload and average resolution time per assignment group
SELECT g.group_name,
       COUNT(*) AS incidents,
       ROUND(AVG(i.resolution_hours), 1) AS avg_resolution_hours
FROM incidents i
JOIN assignment_groups g ON g.group_id = i.group_id
GROUP BY g.group_name
ORDER BY incidents DESC;

-- Q4. Monthly incident volume
SELECT SUBSTR(opened_at, 1, 7) AS month, COUNT(*) AS incidents
FROM incidents
GROUP BY month
ORDER BY month;

-- Q5. Categories with the slowest average resolution
SELECT category,
       COUNT(*) AS resolved_tickets,
       ROUND(AVG(resolution_hours), 1) AS avg_resolution_hours
FROM incidents
WHERE resolution_hours IS NOT NULL
GROUP BY category
ORDER BY avg_resolution_hours DESC;
