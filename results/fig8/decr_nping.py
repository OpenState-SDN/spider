# execute it with $sudo eval `python decr_ping.py`

import random
import os,sys

if len(sys.argv)!=4:
    print("You need to specify [destination IP] [peak rate] [step]!")
    sys.exit()

ping_host = sys.argv[1]


peak_rate = int(sys.argv[2]) #pkt/s - Start from this rate...
time_step = 1 #seconds - ...every time_step seconds...
rate_step = int(sys.argv[3]) #pkt/s - ...decrease the rate of rate_step...
peak_time = 5 #seconds - allow peak_time seconds of peak rate at the beginning...

num_flows = peak_rate / rate_step
sleep_int = 1.0 / peak_rate
flow_pkt_interarrival = peak_rate
tot_duration = num_flows * time_step
welcome_msg = "Starting experiment... ETA {} seconds".format(tot_duration)

flows = []
for i in range(1,num_flows+1):
    # sleep between pings so to (hopefully) have a equally spaced packets
    flows.append("sleep 1; nping --rate {} --count {} --icmp-type 0 {} --quiet &".format(
        flow_pkt_interarrival, flow_pkt_interarrival, ping_host))
    flow_pkt_interarrival -= rate_step
#Uncomment if you want to generate traffic at increasing rate 
'''
flows.append("sleep 10;")
for i in range(1,num_flows+1):
    flow_pkt_interarrival += rate_step
    # sleep between pings so to (hopefully) have a equally spaced packets
    flows.append("sleep 1; nping --rate {} --count {} --icmp-type 0 {} &".format(
        flow_pkt_interarrival, flow_pkt_interarrival, ping_host))
'''
# start flows in random order to minimize bursty behavior
command = " ".join(flows)
print command
os.system(command)