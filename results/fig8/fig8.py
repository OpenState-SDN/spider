import pcapy, glob, os
from pcapy import open_offline
import impacket
from impacket.ImpactDecoder import EthDecoder, LinuxSLLDecoder
from pprint import pprint
import matplotlib
# Force matplotlib to not use any Xwindows backend.
#matplotlib.use('Agg')
import matplotlib.pyplot as plt
import re
import subprocess
import distutils.spawn

################################################################################################################################
#  CONFIGURATION                                                                                                               #
################################################################################################################################

# Number of realizations
REALIZATIONS_NUM = 1

# Incoming traffic initial rate
PEAK_RATE = 200 # pkt/s

# Decreasing step for incoming traffic 
STEP = 2 # pkt/sec

# Range of Heartbeat requests rates
HB_RATE_VALUES = [10,40,70,100]

# Outgoing traffic rate
TRAFFIC_RATE = 1000

################################################################################################################################
################################################################################################################################

# TOPOLOGY

#            ----s5------
#          /             \
# s1 -- s2 -- s7 -- s3 -- s4 -- s6
#              |     |     |     |
#             [H7]  [H3]  [H4]  [H6]

# demand H3->H6 is forwarded on path s3-s4-s6
# demand H4->H7 is forwarded on path s4-s3-s7
# demand H6->H3 is forwarded on path s6-s4-s5-s2 s7-s3
# demand H7->H4 is forwarded on path s7-s2-s5-4s

# The analized link is (S3-S4)
# H3 generates traffic towards H6 at constant rate (TRAFFIC_RATE pkt/sec)
# In absence of traffic coming from the opposite direction, this is used to trigger HB messages
# H4 generates traffic towards H7 adecreasing rate (from PEAK_RATE to 0 pkt/sec)

if os.geteuid() != 0:
    exit("You need to have root privileges to run this script")

# Check if nmap is installed
def is_tool(name):
    return distutils.spawn.find_executable(name) is not None

if not is_tool('nmap'):
    subprocess.call("sudo apt-get -q -y install nmap".split())


numbers = re.compile(r'(\d+)')
def numericalSort(value):
    parts = numbers.split(value)
    parts[1::2] = map(int, parts[1::2])
    return parts

# These two classes are needed to parse pcap files
class Connection:
    """ This class can be used as a key in a dictionary to select a connection """

    def __init__(self, p1):
        """ This constructor takes one tuple. The 1st element is the IP address as a string, and the 2nd is the port as an integer. """
        self.p1 = p1

    def __cmp__(self, other):
        if (self.p1 == other.p1):
            return 0
        else:
            return -1

    def __hash__(self):
        return (hash(self.p1[0]) ^ hash(self.p1[1]))

class Decoder:
    def __init__(self, pcapObj):
        # Query the type of the link and instantiate a decoder accordingly.
        datalink = pcapObj.datalink()
        if pcapy.DLT_EN10MB == datalink:
            self.decoder = EthDecoder()
        elif pcapy.DLT_LINUX_SLL == datalink:
            self.decoder = LinuxSLLDecoder()
        else:
            raise Exception("Datalink type not supported: " % datalink)

        self.pcap = pcapObj
        self.individual_counters = 0
        

    def start(self):
        # Sniff ad infinitum. PacketHandler shall be invoked by pcap for every packet.
        self.pcap.loop(0, self.packetHandler)
        return self.individual_counters

    def packetHandler(self, hdr, data):
        self.individual_counters += 1 

FIG8_BASE_DIR = "/home/mininet/spider/results/fig8"

# Range of values for Heartbeat requests generation timeout
DELTA_6_VALUES = ['%.6f' % (1/float(i)) for i in HB_RATE_VALUES]

delete_all_folders=True
if len(glob.glob(FIG8_BASE_DIR+"/HB_req_TO_*"))>0:
    msg="Some SIMULATIONS folders have been found! Do you want to delete them?"
    delete_all_folders = True if raw_input("%s (y/N) " % msg).lower() == 'y' else False

if (delete_all_folders):
    os.system("rm -fr "+FIG8_BASE_DIR+"/HB_req_TO_*")

    os.environ['TRAFFIC_RATE'] = str(TRAFFIC_RATE)
    os.environ['PEAK_RATE'] = str(PEAK_RATE)
    os.environ['STEP'] = str(STEP)

    # NB: one realization produces one instance of a plot of fig8.
    # After fixing hb_rate, each realization is repeated REALIZATIONS_NUM times by calling fig8_ryu_app.
    # Finally all the instances are vertically averaged.
    tot_sim=len(HB_RATE_VALUES)*REALIZATIONS_NUM
    curr_sim = 0 # index of current simulation
    for delta_6 in DELTA_6_VALUES:
        for realiz_num in range(REALIZATIONS_NUM):
            curr_sim+=1

            # Close mininet/Ryu instances
            os.system("sudo kill -9 $(pidof -x ryu-manager) 2> /dev/null")
            os.system("sudo mn -c 2> /dev/null")
            os.system("cd /var/log; > syslog;")

            print "\n\x1B[31mSTARTING SIMULATION #"+str(curr_sim)+" of "+str(tot_sim)+" - [delta_6: "+str(delta_6)+"] realization #"+str(realiz_num+1)+" of "+str(REALIZATIONS_NUM)+" - "+str(100*curr_sim/tot_sim)+"%\x1B[0m\n"

            os.environ['realiz_num'] = str(realiz_num+1)
            os.environ['delta_6'] = str(delta_6)
            os.system('ryu-manager fig8_ryu_app.py')

# for each PCAP file we extract rates of data and probe
individual_counters={} # contains the number of data/prove packets for each '1-second' slot, for each HB_rate, for each realization
average_counters={} # it's the same as individual_counters but vertically averaged over the realizations

for delta_6_idx,delta_6 in enumerate(DELTA_6_VALUES):
    individual_counters[delta_6] = {}
    for realiz_num in range(REALIZATIONS_NUM):
        individual_counters[delta_6][realiz_num] = {}
        # there's only one pcap in each folder, so this 'for' has just one iteration
        for pcap in glob.glob(FIG8_BASE_DIR+"/HB_req_TO_"+str(delta_6)+"/realiz_"+str(realiz_num+1)+"/*pcap"):
            print 'Parsing '+pcap

            os.system("rm -rf "+os.path.dirname(pcap)+"/split; mkdir "+os.path.dirname(pcap)+"/split ")
            # pcap file is splitted in many files of 1 second: split_{second}_{date_hour}.pcap
            os.system("editcap -i 1 "+pcap+" "+os.path.dirname(pcap)+"/split/split.pcap")
            for splitted_pcap in glob.glob(os.path.dirname(pcap)+"/split/*pcap"):
                sec = int(splitted_pcap.split('_')[-2])
                individual_counters[delta_6][realiz_num][sec] = {}

                # Open file
                p = open_offline(splitted_pcap)
                p.setfilter(r'(mpls 16 && dst host 10.0.0.7)') # BPF syntax
                # Start decoding process.
                individual_counters[delta_6][realiz_num][sec]['data']=Decoder(p,).start()
                
                # Open file
                p = open_offline(splitted_pcap)
                p.setfilter(r'(mpls 21 && dst host 10.0.0.6)') # BPF syntax
                # Start decoding process.
                individual_counters[delta_6][realiz_num][sec]['probe']=Decoder(p,).start()

    average_counters[delta_6] = {}
    for realiz_num in range(REALIZATIONS_NUM):
        for pcap in glob.glob(FIG8_BASE_DIR+"/HB_req_TO_"+str(delta_6)+"/realiz_"+str(realiz_num+1)+"/*pcap"):
            for sec in individual_counters[delta_6][realiz_num]:
                if sec not in average_counters[delta_6]:
                    average_counters[delta_6][sec] = {'data': 0, 'probe': 0}
                average_counters[delta_6][sec]['data'] += individual_counters[delta_6][realiz_num][sec]['data']
                average_counters[delta_6][sec]['probe'] += individual_counters[delta_6][realiz_num][sec]['probe']

    for sec in average_counters[delta_6]:
        average_counters[delta_6][sec]['data'] = average_counters[delta_6][sec]['data']/REALIZATIONS_NUM
        average_counters[delta_6][sec]['probe'] = average_counters[delta_6][sec]['probe']/REALIZATIONS_NUM

    # each plot has 3 lines (data, probe, data+probe)
    data = []
    for idx,i in enumerate(average_counters[delta_6]):
        data.append(average_counters[delta_6][idx]['data'])
    probe = []
    for idx,i in enumerate(average_counters[delta_6]):
        probe.append(average_counters[delta_6][idx]['probe'])
    tot = []
    for idx,i in enumerate(average_counters[delta_6]):
        tot.append(average_counters[delta_6][idx]['probe']+average_counters[delta_6][idx]['data'])
    x = range(len(average_counters[delta_6]))

    print 'DATA coordinates for LateX'
    for i in x:
        print((i,data[i]))
    print
    print 'PROBE coordinates for LateX'
    for i in x:
        print((i,data[i]))
    print
    print 'PROBE+DATA coordinates for LateX'
    for i in x:
        print((i,data[i]))
    print

    fig = plt.figure()
    ax1 = fig.add_subplot(111)
    ax1.set_xlim([0,len(tot)-2])
    ax1.set_ylim([0,max(data)+100])
    ax1.set_ylabel('[pkt/sec]')
    ax1.set_xlabel('[sec]')
    ax1.set_position([0.05,0.05,0.9,0.9])

    ax1.plot(x,data,'--',color='black',label='Data: from '+str(PEAK_RATE)+' to 0 [pkt/sec]')
    ax1.plot(x,probe,':',color='black',label='HB_reply:' + str(HB_RATE_VALUES[delta_6_idx])+' [pkt/sec]')
    ax1.plot(x,tot,color='black',label='Total')
    plt.legend(loc="best", bbox_to_anchor=[0.99,0.99],
           ncol=1, shadow=True, title="HB Overhead", fancybox=True)
    plt.savefig(FIG8_BASE_DIR+'/fig8_HB_rate_'+str(HB_RATE_VALUES[delta_6_idx])+'.png',dpi=400)

    print 'Close the plot to continue...'
    plt.show()
