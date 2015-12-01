import os,glob
import datetime,time
from pprint import pprint
import matplotlib
# Force matplotlib to not use any Xwindows backend.
matplotlib.use('Agg')
import matplotlib.pyplot as plt 
import matplotlib.patches as mpatches
import itertools
from matplotlib.ticker import FixedLocator
import subprocess
import distutils.spawn

if os.geteuid() != 0:
	exit("You need to have root privileges to run this script")

# Check if hping3 is installed
def is_tool(name):
 	return distutils.spawn.find_executable(name) is not None

if not is_tool('hping3'):
	subprocess.call("sudo apt-get -q -y install hping3".split())

os.system("kill -9 $(pidof -x ryu-manager) 2> /dev/null")
os.system('sudo mn -c 2> /dev/null')

SIMULATIONS_NUM = 10#10
INTERARRIVAL_VALUES = [0.001]# [1 , 0.1 , 0.01 , 0.001] # Actually INTERARRIVAL is INTERDEPARTURE from the host
PING_NUM_VALUES = [20000]# [20 , 200 , 2000 , 20000]
LINK_DOWN       = [10]# , 10 , 10 , 10]
LINK_UP         = [10]# , 10 , 10 , 10]
DELTA_6_VALUES = [1.0]
for i in range(10): #10
	DELTA_6_VALUES.append(round(DELTA_6_VALUES[-1]/2,3))
#DELTA_6_VALUES=[1.0, 0.5, 0.25, 0.125, 0.063, 0.032, 0.016, 0.008, 0.004, 0.002, 0.001]
DELTA_7_VALUES = [0.1 , 0.05 , 0.025 , 0.01]
delta_5 = 20

os.environ['DELTA_6_VALUES'] = str(DELTA_6_VALUES)
os.environ['delta_5'] = str(delta_5)

results = {}
results_avg = {}
results_avg_positive_only = {}
# results = { interarrival : { delta_7 : [{ delta_6_a : losses_a , delta_6_b : losses_b } , { delta_6_a : losses_a , delta_6_b : losses_b }] } }
# results_avg = { interarrival : { delta_7 : { delta_6_a : losses_a , delta_6_b : losses_b } } }

ts = time.time()
st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
with open("SPIDER_results_final.txt", "a+") as out_file:
	out_file.write("Simulation started "+str(st)+"\n")

tot_sim=len(INTERARRIVAL_VALUES)*len(DELTA_7_VALUES)*SIMULATIONS_NUM # total number of simulations, without 
i=0 # index of current simulation
for idx,interarrival in enumerate(INTERARRIVAL_VALUES):
	results[interarrival] = {}
	results_avg[interarrival] = {}
        results_avg_positive_only[interarrival] = {}
	os.environ['INTERARRIVAL'] = str(interarrival)
	os.environ['PING_NUM'] = str(PING_NUM_VALUES[idx])
	os.environ['LINK_DOWN'] = str(LINK_DOWN[idx])
	os.environ['LINK_UP'] = str(LINK_UP[idx])

	for delta_7 in DELTA_7_VALUES:
		os.environ['delta_7'] = str(delta_7)
		results[interarrival][delta_7] = []
		results_avg[interarrival][delta_7] = {}
                results_avg_positive_only[interarrival][delta_7] = {}
		for sim_num in range(SIMULATIONS_NUM):
			i+=1
			print('\n\x1B[31mSTARTING SIMULATION #'+str(i)+" of "+str(tot_sim)+" - [interarrival: "+str(interarrival)+" - delta_7: "+str(delta_7)+" ("+str(sim_num+1)+"/"+str(SIMULATIONS_NUM)+") ] - "+str(100*i/tot_sim)+'%\x1B[0m\n')
			os.system("> /var/log/syslog")
                        os.system("rm -f ~/ping.*txt")
			os.system('ryu-manager fig7_ryu_app.py')

			in_file = open("SPIDER_results.txt","r")
			results[interarrival][delta_7].append(eval(in_file.read()))
			in_file.close()
		# results[interarrival][delta_7] = [ {0.001: 1, 0.01: 9, 0.1: 5, 1: 5} , {0.001: 1000, 0.01: 9, 0.1: 5, 1: 5} ]
		for delta_6 in results[interarrival][delta_7][0]:
			values = [ results[interarrival][delta_7][x][delta_6] for x in range(len(results[interarrival][delta_7])) ]
                        values_positive_only = [ results[interarrival][delta_7][x][delta_6] for x in range(len(results[interarrival][delta_7])) if results[interarrival][delta_7][x][delta_6]>0]
			results_avg[interarrival][delta_7][delta_6] = sum(values)/float(len(values))
                        results_avg_positive_only[interarrival][delta_7][delta_6] = sum(values_positive_only)/float(len(values_positive_only))

ts = time.time()
st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
with open("SPIDER_results_final.txt", "a+") as out_file:
	out_file.write("results="+str(results)+"\n")
	out_file.write("results_avg="+str(results_avg)+"\n")
        out_file.write("results_avg_positive_only="+str(results_avg_positive_only)+"\n")
	out_file.write("SIMULATIONS_NUM = "+str(SIMULATIONS_NUM)+"\n")
	out_file.write("INTERARRIVAL_VALUES = "+str(INTERARRIVAL_VALUES)+"\n")
	out_file.write("PING_NUM_VALUES = "+str(PING_NUM_VALUES)+"\n")
	out_file.write("LINK_DOWN = "+str(LINK_DOWN)+"\n")
	out_file.write("LINK_UP = "+str(LINK_UP)+"\n")
	out_file.write("DELTA_6_VALUES = "+str(DELTA_6_VALUES)+"\n")
	out_file.write("DELTA_7_VALUES = "+str(DELTA_7_VALUES)+"\n")
	out_file.write("Simulation finished "+str(st)+"\n\n")

os.system("chown mininet:mininet SPIDER_results_final.txt")
os.system("chown mininet:mininet SPIDER_results.txt")

print
print("SIMULATIONS_NUM = "+str(SIMULATIONS_NUM))
print("INTERARRIVAL_VALUES = "+str(INTERARRIVAL_VALUES))
print("PING_NUM_VALUES = "+str(PING_NUM_VALUES))
print("LINK_DOWN = "+str(LINK_DOWN))
print("LINK_UP = "+str(LINK_UP))
print("DELTA_6_VALUES = "+str(DELTA_6_VALUES))
print("DELTA_7_VALUES = "+str(DELTA_7_VALUES))

print
print("results_avg = { interarrival_a : { delta_7_a : { delta_6_a : losses_a , delta_6_b : losses_b } ,  ... } ,  ...  }")
print
print("[results_avg]")
for interarrival in results_avg:
	print('interarrival = '+str(interarrival))
	pprint(results_avg[interarrival])
	print
print("[results_avg_positive_only]")
for interarrival in results_avg_positive_only:
        print('interarrival = '+str(interarrival))
        pprint(results_avg_positive_only[interarrival])


for interarrival in results_avg_positive_only:
        f,ax = plt.subplots()
        f.set_size_inches(19,12)
        x = sorted(results_avg_positive_only[interarrival].values()[0].keys(),reverse=True)
        fake_x = range(len(x))
        marker = itertools.cycle(('D','^','s','o'))

        for delta_7 in sorted(results_avg_positive_only[interarrival],reverse=True):
                y = [results_avg_positive_only[interarrival][delta_7][delta_6] for delta_6 in x]
                ax.plot(fake_x,y,marker=marker.next(),color='black',label=str(delta_7)+' s',markersize=15,linewidth=3)

        plt.legend(loc=1,prop={'size':36})
        ax.set_ylabel('Losses', fontsize=32)
        ax.set_xlabel('delta_6 [sec]', fontsize=32)
        ax.xaxis.set_major_locator(FixedLocator(fake_x))
        ax.set_xticklabels(x)
        plt.savefig("/home/mininet/SPIDER_losses_rate_"+str(int(1/interarrival))+".png",dpi=50)
        plt.clf()