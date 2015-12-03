import commands

N=[]
diz = {}
for filename in ['E2E','greedy']:
    s = commands.getstatusoutput('cat tmp/*x*'+filename+'*')[1]
    for i in s.split("\n"):
        diz[eval(i)[0]]=eval(i)[1]
        if int(eval(i)[0].split("x")[0]) not in N:
            N.append(int(eval(i)[0].split("x")[0]))
N=sorted(N)
print """\\begin{table*}[]
\\centering
\\caption{Number of flow entries per node.}
\\label{table:BigO}
\\begin{tabular}{llllllllllll}
\\toprule
\\textbf{Net} & \\textbf{D} & \\textbf{E} & \\textbf{C} & \\textbf{min} & \\textbf{avg} & \\textbf{max} & $E^2\\times N$ \\\\ \\midrule"""
for n in N:    
    e = (4*n)-4
    c = (n-2)*(n-2)
    d = e*(e-1)
    print ("{} & {} & {} & {} & {} & {} & {} & {} \\\\".format(str(n)+"x"+str(n), d, e, c, diz[str(n)+"x"+str(n)+" E2E PP"]["min"],int(round(diz[str(n)+"x"+str(n)+" E2E PP"]["avg"])),diz[str(n)+"x"+str(n)+" E2E PP"]["max"], e*e*(e+c))),
    if n != N[-1]:
	print("\\hline")
print """
\\bottomrule
\\end{tabular}
\\end{table*}
"""



'''

\begin{table}[]
\centering
\caption{Number of flow entries per node.}
\label{table:BigO}
\begin{tabular}{llllllllllll}
\toprule
\textbf{Net} & \textbf{D} & \textbf{E} & \textbf{C} & \textbf{min} & \textbf{avg} & \textbf{max} & $E^2\times N$ \\ \midrule
5x5 & 240 & 16 & 9 & 402 & 727 & 934 & 6400 \\ \hline
6x6 & 380 & 20 & 16 & 497 & 1046 & 1490 & 14400 \\ \hline
7x7 & 552 & 24 & 25 & 720 & 1578 & 2280 & 28224 \\ \hline
8x8 & 756 & 28 & 36 & 998 & 2117 & 3523 & 50176 \\ \hline
9x9 & 992 & 32 & 49 & 1273 & 2744 & 4318 & 82944 \\ \hline
10x10 & 1260 & 36 & 64 & 1121 & 3421 & 5708 & 129600 \\ \hline
11x11 & 1560 & 40 & 81 & 1359 & 4061 & 7213 & 193600 \\ \hline
12x12 & 1892 & 44 & 100 & 1127 & 4915 & 9106 & 278784 \\ \hline
13x13 & 2256 & 48 & 121 & 1989 & 5977 & 10486 & 389376 \\ \hline
14x14 & 2652 & 52 & 144 & 1404 & 6892 & 14536 & 529984 \\ \hline
15x15 & 3080 & 56 & 169 & 3576 & 8171 & 15522 & 705600 \\ 

\bottomrule
\end{tabular}
\end{table}'''