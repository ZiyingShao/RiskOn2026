You are stocking a jeweler's retail vault. Below is the complete wholesale inventory available to you, one stone per line:

id,carat,cut,clarity,price_chf,volume_mm3
0,0.53,Very Good,SI2,1110,87.6
1,0.9,Fair,SI1,4796,143.8
2,0.88,Ideal,SI2,3619,144.0
3,1.02,Ideal,VS1,8545,166.9
4,0.31,Ideal,SI1,732,51.1
5,0.91,Ideal,SI1,4922,148.4
6,0.32,Very Good,IF,1018,53.9
7,0.91,Very Good,SI2,3181,148.2
8,0.55,Ideal,SI1,1134,92.1
9,0.91,Premium,SI2,3639,141.2
10,0.46,Ideal,SI1,934,76.2
11,0.3,Ideal,SI1,675,49.8
12,0.76,Very Good,SI2,2347,124.2
13,0.34,Good,SI1,490,55.9
14,0.34,Ideal,SI1,803,54.7
15,0.3,Very Good,VS1,681,49.3
16,0.51,Ideal,VS1,1599,85.4
17,0.43,Ideal,VVS2,1408,70.6
18,0.41,Ideal,VVS2,1007,67.0
19,0.23,Ideal,VVS2,530,38.0
20,1.71,Premium,SI1,14882,278.4
21,0.31,Very Good,SI1,507,52.2
22,1.24,Premium,VVS2,10388,204.7
23,0.43,Very Good,SI1,774,71.7
24,0.3,Very Good,VVS1,638,48.1
25,1.16,Very Good,SI1,4657,187.8
26,0.32,Very Good,VS2,657,52.6
27,0.43,Premium,SI1,774,68.5
28,0.37,Ideal,VS2,876,62.3
29,0.37,Premium,SI1,708,61.7
30,0.5,Very Good,SI1,1415,81.2
31,1.7,Very Good,VS2,11190,282.8
32,1.01,Very Good,SI2,4355,162.1
33,0.33,Premium,IF,891,54.7
34,1.0,Good,VS2,6050,164.2
35,0.53,Ideal,SI1,1268,87.4
36,1.01,Very Good,IF,7974,159.6
37,0.32,Premium,VS1,421,52.2
38,0.31,Good,VVS1,707,50.3
39,0.24,Premium,VVS1,432,39.2
40,0.32,Ideal,VS2,768,53.4
41,0.7,Very Good,VS1,4095,116.1
42,0.5,Good,VS2,1433,82.0
43,1.01,Premium,VS1,6499,165.7
44,1.2,Very Good,SI1,6973,191.1
45,0.43,Ideal,SI1,783,71.1
46,0.4,Premium,SI1,900,64.7
47,0.32,Premium,VS2,720,54.5
48,1.01,Premium,SI1,4338,156.9
49,0.51,Good,VS2,1665,80.8
50,0.66,Very Good,VS1,1978,105.7
51,1.2,Premium,SI1,5098,196.2
52,0.71,Ideal,VS2,3153,115.4
53,0.41,Ideal,VVS1,875,67.6
54,0.32,Very Good,VS1,505,51.0
55,0.86,Premium,SI2,2757,140.8
56,1.02,Ideal,VS1,6857,164.7
57,0.4,Ideal,SI1,573,66.6
58,1.5,Premium,VS2,12196,243.0
59,1.3,Premium,VVS1,14068,212.4

Select the subset of stones that MAXIMISES total carat mass, subject to:
- total price of selected stones <= CHF 20,000
- at most 12 stones
- total volume of selected stones <= 2,000 mm3
- no single cut grade may exceed 40% of the stones selected

Reply with ONLY this JSON and nothing else:
{"selected": [<ids>], "total_carat": <number>, "total_price": <number>}
