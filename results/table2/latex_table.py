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