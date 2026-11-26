-- OPSPULSE workforce analytics: technician workload and performance.
-- Run:  python src/run_query.py sql/workforce.sql

-- W1. Technician scorecard: volume, open backlog, SLA, speed and quality per technician.
--     "SLA time used" divides resolution time by the SLA target, so a P1 fixed in 0.5 h (50%)
--     and a P4 fixed in 12 h (50%) count as equally fast. That makes technicians with
--     different priority mixes comparable.
SELECT i.assigned_to                                              AS technician,
       COUNT(*)                                                   AS tickets,
       SUM(i.resolved_at IS NULL)                                 AS open_now,
       ROUND(AVG(i.sla_met) * 100, 1)                             AS sla_pct,
       SUM(i.sla_met = 0)                                         AS breaches,
       ROUND(AVG(i.resolution_hours), 2)                          AS avg_hours,
       ROUND(AVG(i.resolution_hours / p.sla_target_hours) * 100, 1) AS sla_time_used_pct,
       ROUND(AVG(i.reopen_count > 0) * 100, 1)                    AS reopen_pct
FROM incidents i
JOIN priorities p ON p.priority = i.priority
GROUP BY i.assigned_to
ORDER BY tickets DESC;

-- W2. Workload compared with the technician's own team (window function).
--     load_vs_team > 100 means the technician handles more than the team average.
WITH per_tech AS (
    SELECT g.group_name AS team, i.assigned_to AS technician, COUNT(*) AS tickets
    FROM incidents i
    JOIN assignment_groups g ON g.group_id = i.group_id
    WHERE g.group_name <> 'Unassigned'
    GROUP BY g.group_name, i.assigned_to
)
SELECT team, technician, tickets,
       ROUND(AVG(tickets) OVER (PARTITION BY team), 0)                     AS team_avg,
       ROUND(100.0 * tickets / AVG(tickets) OVER (PARTITION BY team), 0)   AS load_vs_team,
       RANK() OVER (PARTITION BY team ORDER BY tickets DESC)               AS rank_in_team
FROM per_tech
ORDER BY team, rank_in_team;

-- W3. Team capacity: how many tickets each technician in a team carries on average.
SELECT g.group_name                                      AS team,
       COUNT(DISTINCT i.assigned_to)                     AS technicians,
       COUNT(*)                                          AS tickets,
       ROUND(1.0 * COUNT(*) / COUNT(DISTINCT i.assigned_to), 0) AS tickets_per_technician,
       ROUND(AVG(i.sla_met) * 100, 1)                    AS sla_pct,
       SUM(i.sla_met = 0)                                AS breaches
FROM incidents i
JOIN assignment_groups g ON g.group_id = i.group_id
WHERE g.group_name <> 'Unassigned'
GROUP BY g.group_name
ORDER BY tickets_per_technician DESC;

-- W4. Data quality check: tickets with a technician but no assignment group.
SELECT COUNT(*) AS tickets_with_technician_but_no_group
FROM incidents i
JOIN assignment_groups g ON g.group_id = i.group_id
WHERE g.group_name = 'Unassigned' AND i.assigned_to IS NOT NULL;
