import os,glob
import json
import matplotlib
# Force matplotlib to not use any Xwindows backend.
matplotlib.use('Agg')
import matplotlib.pyplot as plt 
import matplotlib.patches as mpatches
import math
from datetime import datetime
import numpy as np
import time
import operator
from pprint import pprint
import itertools

################################################################################################################################
#  CONFIGURATION                                                                                                               #
################################################################################################################################

# Number of realizations
REALIZATIONS_NUM = 20

INDIVIDUAL_TRAFFIC_RATE = 100 # [pkt/sec]
REQUESTS_RANGE = [5,10,15,20,25,30,35]

LINK_DOWN = 5 # [sec]
LINK_UP   = 5 # [sec]
ENABLE_FAULT = 'yes'

# additional delay switch-controller, in ms (OF only)
RTT_DELAY_LIST = [0,3,6,12] # [ms]

# detection timeouts (SPIDER only)
delta_6 = 0.002 # sec]
delta_7 = 0.001 # [sec]
delta_5 = 20    # [sec]

################################################################################################################################
################################################################################################################################

if os.geteuid() != 0:
	exit("You need to have root privileges to run this script")

	os.system('sudo tc qdisc add dev lo root netem delay 0ms')
	os.system('sudo tc qdisc change dev lo root netem delay 0ms')

	delete_all_files=True
	if len(glob.glob("/home/mininet/ping*.txt"))>0:
		msg="Some ping TXT files have been found! Do you want to delete them?"
		delete_all_files = True if raw_input("%s (y/N) " % msg).lower() == 'y' else False

		if delete_all_files==False:
			exit()

			if len(glob.glob("/home/mininet/ping*.bak"))>0:
				print("Some ping BAK files have been found! Save them or remove them :)\nrm -f ~/*.bak")
				exit()

# Remove old data
os.system('rm /home/mininet/ping*.txt')

# Close mininet/Ryu instances
os.system("kill -9 $(pidof -x ryu-manager) 2> /dev/null")
os.system("sudo mn -c 2> /dev/null")

# Environment variables
os.environ['interarrival'] = str(1/float(INDIVIDUAL_TRAFFIC_RATE))
os.environ['LINK_DOWN'] = str(LINK_DOWN)
os.environ['LINK_UP'] = str(LINK_UP)
os.environ['ENABLE_FAULT'] = ENABLE_FAULT
os.environ['RTT_DELAY_LIST'] = str(RTT_DELAY_LIST)
os.environ['REALIZATIONS_NUM'] = str(REALIZATIONS_NUM)
os.environ['delta_6'] = str(delta_6)
os.environ['delta_7'] = str(delta_7)
os.environ['delta_5'] = str(delta_5)

# packets lost because no reply packet has been received (extracted from ping output)
tot_lost_ping_OF={}			# {N1: {RTT1: [tot_losses_1,tot_losses_2,..] , RTT2: [tot_losses_1,tot_losses_2,..] , ...} , N2: {...} , ...}
tot_lost_ping_SPIDER={}		# {N1: [tot_losses_1,tot_losses_2,..] , N2: [tot_losses_1,tot_losses_2,..] , ...}

# NB: one realization produces one point of of each curve of fig7.
# Each realization is repeated REALIZATIONS_NUM times.
# total number of realizations
tot_sim=len(REQUESTS_RANGE)*2

i=1 # index of current realization
for N in REQUESTS_RANGE:
	# number of requests generating traffic
	# NB: even if greater than the # of requests passing from the wrost link, there's no problem
	os.environ['N'] = str(N)

	# create results.txt
	f = open('results.txt','w')
	for r in range(1,N+1):
		f.write('set PrimaryPath['+str(r)+'] := 1 2 3 '+str(4+r)+';\n')
		f.write('set PrimaryPath['+str(r+N)+'] := '+str(4+r)+' 3 4 1;\n')
		f.write('\n')

	for r in range(1,N+1):
		f.write('param DetectNode[2,3,'+str(r)+']:= 2;\n')
		f.write('\n')

	for r in range(1,N+1):
		f.write('set DetourPath[2,3,'+str(r)+'] := 1 4 3;\n')
		f.write('\n')

	f.close()

	# TOPOLOGY

	#             -- s4 --    -- s(4+1) -- [H 4+1]
	#            /        \  /
	# [H1] -- s1 -- s2 -- s3 --  s(4+2) -- [H 4+2]
	#                        \
	#                         -- s(4+N) -- [H 4+N]
	#
	# The analized fault is (S2-S3)
	# H1 generates traffic towards H5,H6,...H(4+N)
	# Primary path from H1 to Hx is s1-s2-s3-s(4+x)
	# Backup path  from H1 to Hx is s1-s4-s3-s(4+x)
	# Reverse path from Hx to H1 is s(4+x)-s3-s4-sq

	# create network.xml
	f = open('network.xml','w')
	network_xml_string="""<?xml version="1.0" encoding="ISO-8859-1"?>
	<network xmlns="http://sndlib.zib.de/network" version="1.0">
	<networkStructure>
	<nodes coordinatesType="pixel">
	<node id="N1">
	<coordinates>
	<x>0</x>
	<y>100</y>
	</coordinates>
	</node>
	<node id="N2">
	<coordinates>
	<x>100</x>
	<y>100</y>
	</coordinates>
	</node>
	<node id="N3">
	<coordinates>
	<x>200</x>
	<y>100</y>
	</coordinates>
	</node>
	<node id="N4">
	<coordinates>
	<x>100</x>
	<y>0</y>
	</coordinates>
	</node>
	"""
	f.write(network_xml_string)
	for r in range(1,N+1):
		f.write('   <node id="N'+str(4+r)+'">\n    <coordinates>\n     <x>300</x>\n     <y>'+str(r)+'</y>\n    </coordinates>\n   </node>\n')

		network_xml_string="""  </nodes>
		<links>
		<link id="L1">
		<source>N1</source>
		<target>N2</target>
		</link>
		<link id="L2">
		<source>N2</source>
		<target>N3</target>
		</link>
		<link id="L3">
		<source>N1</source>
		<target>N4</target>
		</link>
		<link id="L4">
		<source>N3</source>
		<target>N4</target>
		</link>
		"""
	f.write(network_xml_string)
	for r in range(1,N+1):
		f.write('   <link id="L'+str(4+r)+'">\n    <source>N3</source>\n    <target>N'+str(4+r)+'</target>\n   </link>\n')

		network_xml_string="""  </links>
		</networkStructure>
		<demands>
		"""
	f.write(network_xml_string)
	for r in range(1,N+1):
		f.write('  <demand id="D'+str(r)+'">\n    <source>N1</source>\n    <target>N'+str(4+r)+'</target>\n   <demandValue>10</demandValue>\n  </demand>\n')
	for r in range(1,N+1):
		f.write('  <demand id="D'+str(r+N)+'">\n    <source>N'+str(4+r)+'</source>\n    <target>N1</target>\n   <demandValue>10</demandValue>\n  </demand>\n')
		network_xml_string=""" </demands>
		</network>

		"""
	f.write(network_xml_string)
	f.close()

	# launch controller
	print('\n\x1B[31mSTARTING OF SIMULATION #'+str(i)+" of "+str(tot_sim)+" (#REQ:"+str(N)+") - "+str(100*i/tot_sim)+'%\n\x1B[0m')
	os.system("> /var/log/syslog")
	os.system('ryu-manager fig9_OF_ryu_app.py')
	os.system("kill -9 $(pidof -x ryu-manager) 2> /dev/null")
	os.system("sudo mn -c 2> /dev/null")
	for delay in RTT_DELAY_LIST:
		for sim_num in range(REALIZATIONS_NUM):
			lost=[] # list of lost packets for each request H1->H(4+x)
			for txt in glob.glob("/home/mininet/ping_OF*."+str(delay)+"rtt.sim"+str(sim_num)+".txt"):
				rx=os.popen("cat "+txt+" | grep transmitted | awk '{print $4}'").read() # received packets
				tx=os.popen("cat "+txt+" | grep transmitted | awk '{print $1}'").read() # transmitted packets
				lost.append(int(tx)-int(rx))
			if N not in tot_lost_ping_OF:
				tot_lost_ping_OF[N] = {}
			if not delay in tot_lost_ping_OF[N]:
				tot_lost_ping_OF[N][delay] = []
			tot_lost_ping_OF[N][delay].append(sum(lost)) # total number of packets with no reply
			#os.system('for file in /home/mininet/ping_OF*.'+str(delay)+'rtt.sim'+str(sim_num)+'.txt; do mv "$file" "${file%.txt}'+'.OF.simnum'+str(sim_num)+'.bak"; done')
			os.system('for file in /home/mininet/ping_OF*.'+str(delay)+'rtt.sim'+str(sim_num)+'.txt; do rm "$file"; done')
	i+=1

	# launch controller
	print('\n\x1B[31mSTARTING SPIDER SIMULATION #'+str(i)+" of "+str(tot_sim)+" (#REQ:"+str(N)+") - "+str(100*i/tot_sim)+'%\n\x1B[0m')
	os.system("> /var/log/syslog")
	os.system('ryu-manager fig9_SPIDER_ryu_app.py')
	os.system("kill -9 $(pidof -x ryu-manager) 2> /dev/null")
	os.system("sudo mn -c 2> /dev/null")
	os.system('sudo tc qdisc change dev lo root netem delay 0ms')
	for sim_num in range(REALIZATIONS_NUM):
		lost=[] # list of lost packets for each request H1->H(4+x)
		for txt in glob.glob("/home/mininet/ping_SPIDER*.sim"+str(sim_num)+".txt"):
			rx=os.popen("cat "+txt+" | grep transmitted | awk '{print $4}'").read() # received packets
			tx=os.popen("cat "+txt+" | grep transmitted | awk '{print $1}'").read() # transmitted packets
			lost.append(int(tx)-int(rx))
		if N not in tot_lost_ping_SPIDER:
			tot_lost_ping_SPIDER[N] = []
		tot_lost_ping_SPIDER[N].append(sum(lost)) # total number of packets with no reply
		#os.system('for file in /home/mininet/ping_SPIDER*.sim'+str(sim_num)+'.txt; do mv "$file" "${file%.txt}'+'.SPIDER.simnum'+str(sim_num)+'.bak"; done')
		os.system('for file in /home/mininet/ping_SPIDER*.sim'+str(sim_num)+'.txt; do rm "$file"; done')
	i+=1

pprint(tot_lost_ping_OF)
pprint(tot_lost_ping_SPIDER)

# tot_lost_ping_OF = {N1: {RTT1: [tot_losses_1,tot_losses_2,..] , RTT2: [tot_losses_1,tot_losses_2,..] , ...} , N2: {...} , ...}
# tot_lost_ping_SPIDER = {N1: [tot_losses_1,tot_losses_2,..] , N2: [tot_losses_1,tot_losses_2,..] , ...}

tot_lost_ping_OF_average={} # {N1: {RTT1: tot_losses_avg , RTT2: tot_losses_avg] , ...} , N2: {...} , ...}
for N in tot_lost_ping_OF:
  tot_lost_ping_OF_average[N]={}
  for delay in tot_lost_ping_OF[N]:
    tot_lost_ping_OF_average[N][delay]=sum(tot_lost_ping_OF[N][delay])/len(tot_lost_ping_OF[N][delay])

tot_lost_ping_SPIDER_average={} # {N1: tot_losses_avg , N2: tot_losses_avg , ...}
for N in tot_lost_ping_SPIDER:
  tot_lost_ping_SPIDER_average[N]=sum(tot_lost_ping_SPIDER[N])/len(tot_lost_ping_SPIDER[N])

print("\ntot_lost_ping_OF_average = {N1: {RTT1: tot_losses , RTT2: tot_losses , ...} , N2: {...} , ...}\n")
print ("tot_lost_ping_OF_average=")
pprint(tot_lost_ping_OF_average)

with open("/home/mininet/total_lost_packets_OF.txt", "a+") as out_file:
    out_file.write("REALIZATIONS_NUM="+str(REALIZATIONS_NUM)+"\nINDIVIDUAL_TRAFFIC_RATE="+str(INDIVIDUAL_TRAFFIC_RATE)+"\nLINK_DOWN="+str(LINK_DOWN)+"\nLINK_UP"+str(LINK_UP))
    out_file.write("\nREQUESTS_RANGE="+str(REQUESTS_RANGE)+"\nRTT_DELAY_LIST="+str(RTT_DELAY_LIST)+"\n")
    out_file.write("tot_lost_ping_OF_average = {N1: {RTT1: tot_losses , RTT2: tot_losses , ...} , N2: {...} , ...}\n")
    out_file.write("tot_lost_ping_OF = "+str(tot_lost_ping_OF)+"\n")
    out_file.write("tot_lost_ping_OF_average = "+str(tot_lost_ping_OF_average)+"\n\n\n")

print("\ntot_lost_ping_SPIDER_average = {N1: tot_losses , N2: ... , ...}\n")
print ("tot_lost_ping_SPIDER_average=")
pprint(tot_lost_ping_SPIDER_average)

with open("/home/mininet/total_lost_packets_SPIDER.txt", "a+") as out_file:
    out_file.write("REALIZATIONS_NUM="+str(REALIZATIONS_NUM)+"\nINDIVIDUAL_TRAFFIC_RATE="+str(INDIVIDUAL_TRAFFIC_RATE)+"\nLINK_DOWN="+str(LINK_DOWN)+"\nLINK_UP"+str(LINK_UP))
    out_file.write("\nREQUESTS_RANGE="+str(REQUESTS_RANGE)+"\n")
    out_file.write("\ndelta_6="+str(delta_6)+"\ndelta_7="+str(delta_7)+"\ndelta_5="+str(delta_5)+"\n")
    out_file.write("tot_lost_ping_SPIDER_average = {N1: tot_losses , N2: ... , ...}\n")
    out_file.write("tot_lost_ping_SPIDER = "+str(tot_lost_ping_SPIDER)+"\n")
    out_file.write("tot_lost_ping_SPIDER_average = "+str(tot_lost_ping_SPIDER_average)+"\n\n\n")

os.system('sudo tc qdisc change dev lo root netem delay 0ms')

# Generate LateX data
# tot_lost_ping_SPIDER_average = {N1: tot_losses_avg , N2: tot_losses_avg , ...}
print('coordinates{')
for N in sorted(tot_lost_ping_SPIDER_average):
    print('  ('+str(N)+','+str(tot_lost_ping_SPIDER_average[N])+')')

print('  };')
print('\\addlegendentry{SPIDER $\delta_7$=1ms}')
print('')
print('##################################################')

# tot_lost_ping_OF_average = {N1: {RTT1: tot_losses_avg , RTT2: tot_losses_avg] , ...} , N2: {...} , ...}
for rtt in RTT_DELAY_LIST:
    print('coordinates{')
    for N in sorted(tot_lost_ping_OF_average):
        print('  ('+str(N)+','+str(tot_lost_ping_OF_average[N][rtt])+')')
    
    print('  };')
    print('\\addlegendentry{OF FF ('+str(rtt)+'ms)}')
    print('')

print('##################################################')

