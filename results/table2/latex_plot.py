import commands

for filename in ['E2E','greedy']:
    print '['+filename+']\n'
    s = commands.getstatusoutput('cat tmp/*x*'+filename+'*')[1]
    d = {}
    for i in s.split("\n"):
        d[eval(i)[0]]=eval(i)[1]
    #print d
    print 'coordinates{'
    for plot_name in d[ d.keys()[0] ]:
        for point in sorted(d, key=lambda d: int(d[:d.index('x')])):
            print '    ('+str(point[:point.index('x')])+','+str(int(d[point][plot_name]))+')'
        print '    };'
        print '\\addlegendentry{'+plot_name+'}'
        print ''
    print '##################################################'