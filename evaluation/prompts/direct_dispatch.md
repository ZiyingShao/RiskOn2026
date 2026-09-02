You are the dispatcher for a ride-hailing platform. Below is the queue of pending customer requests for this shift, and you have 4 drivers available: d1, d2, d3, d4.

Each request line is:
task_id,start_minute,end_minute,passengers,revenue_usd
0,8.8,26.9,1,15.30
1,38.1,57.6,1,15.80
2,12.6,52.8,1,56.80
3,32.0,43.2,1,14.16
4,11.5,27.4,2,18.96
5,33.4,52.6,1,24.96
6,0.2,21.3,2,17.16
7,27.5,43.8,1,17.15
8,3.5,13.9,1,13.30
9,33.4,78.9,1,57.67
10,50.7,58.0,2,9.30
11,30.6,46.4,1,14.80
12,27.6,51.6,1,23.16
13,57.3,67.2,1,12.95
14,35.9,42.9,1,9.30
15,9.1,39.2,1,21.80
16,31.2,50.9,1,18.48
17,57.8,74.5,1,20.76
18,0.0,36.0,2,44.76
19,49.7,58.4,3,11.30
20,29.9,65.2,1,30.80
21,1.5,30.9,1,24.30
22,11.1,23.5,1,11.30
23,34.6,71.4,1,29.30
24,23.3,41.6,1,14.30

Assign requests to drivers to MAXIMISE total revenue, subject to:
- a request may be given to at most one driver (some will go unserved)
- a driver cannot be in two places at once: the trips assigned to any one driver must not overlap in time (a trip occupies its driver from its start_minute until its end_minute)
- a vehicle holds at most 4 passengers

Reply with ONLY this JSON and nothing else:
{"assignments": {"d1": [task_ids], "d2": [task_ids], "d3": [task_ids], "d4": [task_ids]}, "total_revenue": <number>}
