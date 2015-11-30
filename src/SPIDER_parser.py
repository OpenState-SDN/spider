# Copyright 2015 Luca Pollini <luca.pollini@mail.polimi.it>
#                Davide Sanvito <davide2.sanvito@mail.polimi.it>
#                Carmelo Cascone <carmelo.cascone@polimi.it>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import division
from pulp import Amply
import json
import cPickle as pickle
import pprint
import array
import networkx as nx
from xml.dom import minidom
import matplotlib
# Force matplotlib to not use any Xwindows backend.
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os.path
import hashlib
import fnss
import os,glob,subprocess
from mininet.topo import Topo
from mininet.node import Node
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.util import dumpNodeConnections, waitListening
from mininet.log import setLogLevel
from mininet.cli import CLI
from mininet.node import RemoteController,UserSwitch
from mininet.term import makeTerm
from mininet.nodelib import NAT
import ryu.ofproto.ofproto_v1_3 as ofproto
import ryu.ofproto.ofproto_v1_3_parser as ofparser
import ryu.ofproto.openstate_v1_0 as osproto
import ryu.ofproto.openstate_v1_0_parser as osparser
import time

'''
[RF FSM]

d1 IDLE     Flowlet idle TO before switching from PP to detour
d2 HARD     Max hard TO before switching from PP to detour
d3 IDLE     Flowlet idle TO before switching from detour to PP
d4 HARD     Max hard TO before switching from detour to PP

It is possible to reconfigure SPIDER's timeouts at runtime selecting from a pre-defined list

                            d1    d2    d3    d4      d1     d2     d3     d4   '''
flowlet_timeouts_list = [ (0.1 , 1 , 0.1 , 1) , (0.01 , 0.1 , 0.01 , 0.1) ]

'''
[LF FSM]

d5 HARD     Probe generation TO
d6 HARD     Heartbeat request generation TO
d7 HARD     Heartbeat reply TO before declaring down a port

                             d6  d7  d5       d6      d7   d5      d6     d7   d5  '''
detection_timeouts_list = [ (1 , 1 , 10) , ( 0.100 , 0.1 , 10) , (0.01 , 0.1 , 10) ]

selected_detection_timeouts = detection_timeouts_list[0]
selected_flowlet_timeouts = flowlet_timeouts_list[0]

def delta1(timeouts):
    return timeouts[0]

def delta2(timeouts):
    return timeouts[1]

def delta3(timeouts):
    return timeouts[2]

def delta4(timeouts):
    return timeouts[3]

def delta5(timeouts):
    return timeouts[2]

def delta6(timeouts):
    return timeouts[0]

def delta7(timeouts):
    return timeouts[1]

class OFPHashableMatch(ofparser.OFPMatch):
    def __hash__(self):
        return hash(str(self))

    def __eq__(self,other):
        return hash(str(self))==hash(str(other))

def md5sum_results(filename='results.txt'):
    if not os.path.exists(filename):
        return ""
    return hashlib.md5(open(filename).read()).hexdigest()

def check_create_tmp_dir():
    if not os.path.exists('./tmp'):
        os.makedirs('./tmp')

def network_has_changed(new_hash,filename='./tmp/last_results_hash'):
    # if old_hash!=new_hash or old_hash does not exists, it returns True
    if os.path.isfile(filename):
        f=open(filename,'r')
        if (str(new_hash)!=f.read()):
            return True
        else:
            return False
    else:
        return True

def erase_figs_folder(filename='./tmp/last_results_hash',figs_folder='./figs/'):
    print('Erasing figs folder...')
    files = glob.glob(figs_folder+'*')
    for f in files:
        os.remove(f)

def save_hash(new_hash,filename='./tmp/last_results_hash'):
    f=open(filename,'w+')
    f.write(str(new_hash))
    f.close()

def parse_ampl_results_if_not_cached(filename='results.txt'):
    results_hash = md5sum_results(filename)
    save_hash(results_hash)

    if (os.path.isfile('./tmp/' + results_hash + '-requests.p') and os.path.isfile('./tmp/' + results_hash + '-faults.p')):
        print 'Loading cached requests, faults...'
        requests = pickle.load(open('./tmp/' + results_hash + '-requests.p'))
        faults = pickle.load(open('./tmp/' + results_hash + '-faults.p'))
    else:
        print 'Parsing ampl results (it may take a while)...'
        requests, faults = parse_ampl_results(filename)

    return (requests, faults)

def parse_ampl_results(filename='results.txt'):
    results_hash = md5sum_results(filename)
    save_hash(results_hash)

    data = Amply("""
    set PrimaryPath{REQUESTS};
    set DetourPath{NODES, NODES, REQUESTS};
    param DetectNode{NODES, NODES, REQUESTS};
    """)

    data.load_file(open(filename))

    requests = dict()
    faults = dict()
    stats = dict()
    pp_edges = dict()

    print "Parsing requests..."
    for i in data.PrimaryPath:
        rid = int(i)
        pp = [int(x) for x in data.PrimaryPath[rid]]
        pp_edge = (pp[0], pp[-1])
        requests[pp_edge] = {
            'pp_edge': pp_edge,
            'primary_path': pp,
            'faults': dict()}
        pp_edges[rid] = pp_edge
        #print rid, pp_edge, pp

    for i in data.DetectNode.data:

        na = int(i)
        val_na = data.DetectNode.data[na]

        for j in val_na:

            nb = int(j)
            val_nb = val_na[j]

            # if (nb > na):
            #     continue
            # if (nb == 0):
            #     fault_type = 'node'
            #     fid = "N-" + str(na)
            # else:
            #     fault_type = 'link'
            #     fid = "L-" + str(na) + "-" + str(nb)

            for d in val_nb:
                rid = int(d)

                if na < nb:
                    fault_edge = (na, nb)
                else:
                    fault_edge = (nb, na)

                pp_edge = pp_edges[rid]
                pp = requests[pp_edge]['primary_path']

                detect_node = int(val_nb[rid])
                dp = [int(x) for x in data.DetourPath.data[na][nb][rid]]
                redirect_node = dp[0]

                # Fw back path is the sequence of node from detect to redirect node (included)
                idx_d = pp.index(detect_node)
                idx_r = pp.index(redirect_node)
                if(idx_d - idx_r == 0):
                    fw_back_path = None
                else:
                    fw_back_path = pp[idx_r:idx_d + 1]

                fault = {'detect_node': detect_node,
                         'redirect_node': redirect_node,
                         'detour_path': dp,
                         'fw_back_path': fw_back_path}
                # For each request, we populate the corresponding faults...
                requests[pp_edge]['faults'][fault_edge] = fault

                # And viceversa, for each fault, we populate the requests...
                if fault_edge not in faults:
                    faults[fault_edge] = {
                        'requests': {}}

                faults[fault_edge]['requests'][pp_edge] = {
                    'primary_path': pp,
                    'detect_node': detect_node,
                    'redirect_node': redirect_node,
                    'detour_path': dp,
                    'fw_back_path': fw_back_path}

    with open('./tmp/' + results_hash + '-requests.p', 'wb') as fp:
        pickle.dump(requests, fp)
    with open('./tmp/' + results_hash + '-faults.p', 'wb') as fp:
        pickle.dump(faults, fp)

    return requests, faults

def parse_network_xml(filename='network.xml'):
    G = nx.Graph()
    pos = dict()
    # We need to keep track of which nodes are switches and which one are hosts, as G has just 'generic nodes'
    switches = []
    hosts = []

    xmldoc = minidom.parse(filename)
    # Nodes creation
    itemlist = xmldoc.getElementsByTagName('node')
    for s in itemlist:
        n = s.attributes['id'].value
        # Remove the N char at the beginning
        n = int(n[1:])
        switches.append(n)
        G.add_node(n)
        x = s.getElementsByTagName('x')[0].firstChild.data
        y = s.getElementsByTagName('y')[0].firstChild.data
        pos[n] = [float(x), float(y)]

    # Links creation
    itemlist = xmldoc.getElementsByTagName('link')
    for s in itemlist:
        src = s.getElementsByTagName('source')[0].firstChild.data
        src = int(src[1:])
        trg = s.getElementsByTagName('target')[0].firstChild.data
        trg = int(trg[1:])
        G.add_edge(src, trg)

    # mapping is a dict associating node's number with their name, e.g. {4: 's4'}
    mapping = dict([(switches[i], "s%s" % str(switches[i])) for i in range(len(switches))])

    # Hosts creation: if there's a demand NX->NY => 2 hosts hX and hY are created and linked to switches sX and sY
    itemlist = xmldoc.getElementsByTagName('demand')
    for s in itemlist:
        src = s.getElementsByTagName('source')[0].firstChild.data
        src = int(src[1:])
        trg = s.getElementsByTagName('target')[0].firstChild.data
        trg = int(trg[1:])
        count = max(switches + hosts) # find the last used 'generic node' id (NB list1+list2 merges the 2 lists!)
        if "h"+str(src) not in mapping.values():
            hosts.append(count+1)
            mapping[count+1]= "h%s" % str(src)
            G.add_node(count+1)
            G.add_edge(src,count+1)
        count = max(switches + hosts) # find the last used 'generic node' id (NB list1+list2 merges the 2 lists!)
        if "h"+str(trg) not in mapping.values():
            hosts.append(count+1)
            mapping[count+1]= "h%s" % str(trg)
            G.add_node(count+1)
            G.add_edge(trg,count+1)
    # NB: hosts hX won't be associated to X for sure (sX will be)
    print(mapping)

    return (G, pos, hosts, switches, mapping)

def networkx_to_mininet_topo(G, hosts, switches, mapping):
    # Conversion from NetworkX topology into FNSS topology
    fnss_topo = fnss.Topology(G)

    # G is a NetworkX Graph() and fnss_topo is a FNSS Topology(): hosts and switches are indistinguishable 'generic' nodes.
    # We exploit 'mapping' calculated in parse_network_xml() to differentiate them.
    # We can't use fnss.adapters.to_mininet() because we need a customized nodes relabeling.
    # TODO link capacities!! http://fnss.github.io/doc/core/_modules/fnss/adapters/mn.html

    # Conversion from FNSS topology into Mininet topology
    nodes = set(fnss_topo.nodes_iter())
    hosts_set = sorted(set(hosts))
    switches_set = sorted(set(switches))

    hosts_set = set(mapping[v] for v in hosts_set)
    switches_set = set(mapping[v] for v in switches_set)

    if not switches_set.isdisjoint(hosts_set):
        raise ValueError('Some nodes are labeled as both host and switch. '
                         'Switches and hosts node lists must be disjoint')
    if hosts_set.union(switches_set) != switches_set.union(hosts_set):
        raise ValueError('Some nodes are not labeled as either host or switch '
                         'or some nodes listed as switches or hosts do not '
                         'belong to the topology')
    
    fnss_topo = nx.relabel_nodes(fnss_topo, mapping, copy=True)

    mn_topo = Topo()
    for v in switches_set:
        mn_topo.addSwitch(str(v))
    for v in hosts_set:
        mn_topo.addHost(str(v))
    for u, v in fnss_topo.edges_iter():
            params = {}
            mn_topo.addLink(str(u), str(v), **params)

    return mn_topo

def create_mininet_net(mn_topo):
    print "Cleaning previous Mininet instances..."
    os.system('sudo mn -c 2> /dev/null')
    return Mininet(topo=mn_topo, link=TCLink, controller=RemoteController, switch=UserSwitch, cleanup=True, autoSetMacs=False, listenPort=6634)

def launch_mininet(mn_net):
    print "Starting Mininet topology..."
    mn_net.start()

def adapt_mn_topo_ports_to_old_API(ports_dict):
    '''
    Mininet API 2.1.0ps
    mn_topo.ports = {'s3': {'s2': 1, 's4': 2}, 's2': {'s3': 1, 's1': 2, 's5': 3}, ...}

    Mininet API 2.2.0
    mn_topo.ports = {'s3': {1: ('s2', 1), 2: ('s4', 1)}, 's2': {1: ('s3', 1), 2: ('s1', 1), 3: ('s5', 1)}, ...}

    Our parser is based on old API. mn_topo_ports is an adapted version of mn_topo.ports according to the old API
    '''
    old_API_ports_dict = {}
    for key in ports_dict:
        old_API_ports_dict[key]={}
        for key2 in ports_dict[key]:
            old_API_ports_dict[key][ ports_dict[key][key2][0] ] = key2

    return old_API_ports_dict

def mn_setup_MAC_and_IP(mn_net):
    for i in range(len(mn_net.hosts)):
        host_name = str(mn_net.hosts[i])
        host_number = host_name[1:]
        # Assign MAC and IP to the interface towards the network in subnet 10.0/16
        mac_str = int_to_mac_str(int(host_number))  # 'xx:xx:xx:xx:xx:xx'
        ip_str = int_to_ip_str(int(host_number))    # '10.0.x.x'
        mn_net.hosts[i].setMAC(mac_str,'h'+host_number+'-eth0')
        mn_net.hosts[i].setIP(ip_str,16,'h'+host_number+'-eth0')

def mn_setup_static_ARP_entries(mn_net):
    for src in mn_net.hosts:
        for dst in mn_net.hosts:
            if src != dst:
                src.setARP(ip=dst.IP(), mac=dst.MAC())

def draw_network_topology(G,pos,ports_dict,hosts,figs_folder='./figs/'):
    # We need to remove the hosts from the network to draw it, since we have created hosts on demand and we don't have their positions
    G.remove_nodes_from(hosts)
    nx.draw(G, pos, node_size=300, font_size=10, node_color='w', with_labels=True)

    link_to_port={}
    for edge in G.edges():
        link_to_port[(edge[0],edge[1])]=ports_dict['s'+str(edge[0])]['s'+str(edge[1])]
        link_to_port[(edge[1],edge[0])]=ports_dict['s'+str(edge[1])]['s'+str(edge[0])]
    nx.draw_networkx_edge_labels(G, pos, font_color='#B0B0B0', edge_labels=link_to_port, font_size=8,label_pos=0.7)
    
    if not os.path.exists('./figs'):
        os.makedirs('./figs')

    if (os.path.isfile(figs_folder+'network.png')):
        os.remove(figs_folder+'network.png')
    plt.savefig(figs_folder+'network.png', format='PNG', transparent=True)

def create_node_dict(ports_dict,requests):
    # given a node and a request, node_dict[node][req] contains a dict of booleans {'det': True/False, 'red': T/F, 'd&r': T/F} to check the role of a node

    # ports_dict.keys() is ['s3', 's7', ..., 'h1', 'h6', ..., 'h2', 's2']
    # we need to exclude all the 'h*' and remove 's' to obtain [3,7,2]
    nodes=[int(x[1:]) for x in ports_dict.keys() if x[:1]=='s']

    node_dict={}
    for node in nodes:
        node_dict[node]={}
        for k in requests:
            if node in requests[k]['primary_path']:
                node_dict[node][k] = {}
                node_dict[node][k]['det'] = False
                node_dict[node][k]['red'] = False
                node_dict[node][k]['d&r'] = False

    for node in node_dict:
        for r in node_dict[node]:
            for f in requests[r]['faults']:
                if requests[r]['faults'][f]['detect_node'] == node and requests[r]['faults'][f]['redirect_node'] == node:
                    node_dict[node][r]['d&r'] = True
                else:
                    if requests[r]['faults'][f]['detect_node'] == node:
                        node_dict[node][r]['det'] = True
                    if requests[r]['faults'][f]['redirect_node'] == node:
                        node_dict[node][r]['red'] = True

    return node_dict

# given a fault f and a node x, returns True if x is a detect only node for f for at least one request traversing f
def is_detect_given_fault(node,f,node_dict,faults):
    node1=f[0]
    node2=f[1]

    if(node1 > node2):
        node1,node2 = node2,node1

    if not (node1,node2) in faults:
        return False

    for i in faults[(node1,node2)]['requests']:
        if faults[(node1,node2)]['requests'][i]['detect_node']==node and not faults[(node1,node2)]['requests'][i]['redirect_node']==node:
            return True
    return False

# given a fault f and a node x, returns True if x is a detect&redirect node for f for at least one request traversing f
def is_detect_redirect_given_fault(node,f,node_dict,faults):
    node1=f[0]
    node2=f[1]

    if(node1 > node2):
        node1,node2 = node2,node1

    if not (node1,node2) in faults:
        return False

    for i in faults[(node1,node2)]['requests']:
        if faults[(node1,node2)]['requests'][i]['detect_node']==node and faults[(node1,node2)]['requests'][i]['redirect_node']==node:
            return True
    return False

# given a node x and a request req, returns True if x is a detect&redirect node for req
def is_detect_redirect_given_req(x,req,node_dict):
    return node_dict[x][req]['d&r']

# given a node x and a request req, returns True if x is a detect node for req
def is_detect_given_req(x,req,node_dict):
    return node_dict[x][req]['det']

# given a node x and a request req, returns True if x is a redirect node for req
def is_redirect_given_req(x,req,node_dict):
    return node_dict[x][req]['red']

# given a node x, returns True if x is a detect&redirect node for at least 1 request traversing it
def is_detect_redirect(x,node_dict):
    for req in node_dict[x]:
        if node_dict [x][req]['d&r'] == True:
            return True
    return False

# given a node x, returns True if x is a detect only node for at least 1 request traversing it
def is_detect(x,node_dict):
    for req in node_dict[x]:
        if node_dict [x][req]['det'] == True:
            return True
    return False

# given a node x, returns True if x is a redirect only node for at least 1 request traversing it
def is_redirect(x,node_dict):
    for req in node_dict[x]:
        if node_dict [x][req]['red'] == True:
            return True
    return False

def get_mac_match_mininet((src, dst)):
    return dict(eth_src=int_to_mac_str(src), eth_dst=int_to_mac_str(dst))

def openXterm(mn_net,hostname,cmd='bash'):
    makeTerm(node=mn_net[hostname],cmd=cmd)

def pingAll(mn_net):
    for src in mn_net.hosts:
        for dst in mn_net.hosts:
            if src != dst and dst.name!='nat1':
                src.cmd('ping -i 1 '+dst.IP()+'&')

def has_host(node,ports_dict):
    return 'h'+str(node) in ports_dict.keys()

def generate_flow_entries_dict(requests,faults,ports_dict,match_flow,check_cache=False,confirm_cache_loading=True,filename='results.txt',dpctl_script=False):
    if check_cache:
        # if we are generating flow entries for a network without results.txt file, to do caching we hash the fictitious filename instead of the file itself!
        if not os.path.exists(filename):
            results_hash = hashlib.md5(filename).hexdigest()
        else:
            results_hash = md5sum_results(filename)
            
    node_dict = create_node_dict(ports_dict,requests)
    flow_entries_dict = {}                  # associates each node with a list of flow entries
    flow_stats_dict = {}                    # associates each node with flow entries statistics
    flow_entries_with_detection_timeouts_dict = {}     # associates each detection timeout combination with a list of flow entries
    flow_entries_with_flowlet_timeouts_dict = {}       # associates each flowlet timeout combination with a list of flow entries

    # fault_ID dict associate fault (X,Y) with a progressive number, starting from 17 (because MPLS label values 0-15 are reserved).
    # fault_IDs are used for MPLS tags and flow states. Packet tagged with label 16 are packets travelling on the primary path in non-fault conditions.
    f_id=17
    fault_ID={}
    for fault in faults:
        fault_ID[fault] = f_id
        f_id = f_id+1

    # if check_cache is False, flow entries are always regenerated (useful for automated script)
    # if check_cache is True, we search for cached flow entries and ask the user what to do (useful for interactive simulations)
    regenerate_entries=True
    if check_cache:
        if (os.path.isfile('./tmp/' + results_hash + '-flow_entries.p') and os.path.isfile('./tmp/' + results_hash + '-flow_stats.p')):
            if confirm_cache_loading:
                msg="\x1B[31mCached flow entries and stats have been found: do you want to recalculate them?\x1B[0m"
                regenerate_entries = True if raw_input("%s (y/N) " % msg).lower() == 'y' else False
            else:
                regenerate_entries = False

    if not regenerate_entries and check_cache:
        print 'Loading cached flow_entries_dict, flow_stats_dict, flow_entries_with_detection_timeouts_dict, flow_entries_with_flowlet_timeouts_dict...'
        flow_entries_dict = pickle.load(open('./tmp/' + results_hash + '-flow_entries.p'))
        flow_stats_dict = pickle.load(open('./tmp/' + results_hash + '-flow_stats.p'))
        flow_entries_with_detection_timeouts_dict = pickle.load(open('./tmp/' + results_hash + '-timeout.p'))
        flow_entries_with_flowlet_timeouts_dict = pickle.load(open('./tmp/' + results_hash + '-burst.p'))

    else:
        ''' STAGE 0 '''

        # for each switch of the network
        for node in node_dict.keys():
            # table miss
            flow_entry = dict()
            flow_entry['match']=OFPHashableMatch()
            flow_entry['inst']=[ofparser.OFPInstructionGotoTable(1)]
            flow_entry['table_id']=0
            flow_entry['priority']=10
            flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)

            # if 'node' has an host attached => push mpls before going to table 1
            if has_host(node,ports_dict):
                flow_entry = dict()
                flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(node)]['h'+str(node)],eth_src=int_to_mac_str(node))
                flow_entry['actions']=[ofparser.OFPActionPushMpls()]
                flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions']),
                    ofparser.OFPInstructionGotoTable(1)]
                flow_entry['table_id']=0
                flow_entry['priority']=100
                flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)

            # if 'node' is a detect or a det&red towards a port P for at least one request => we want to reset probing timer in detect/det&red FSM of port P when we receive a packet from port P
            for adjacent_node in ports_dict['s'+str(node)]:
                # a node cannot detect failures for the switch-host link => we can skip the check for this port
                if adjacent_node[0]=='h':
                    continue

                adjacent_node_id = int(adjacent_node[1:])

                if is_detect_given_fault(node,(node,adjacent_node_id),node_dict,faults) or is_detect_redirect_given_fault(node,(node,adjacent_node_id),node_dict,faults):
                    inport = ports_dict['s'+str(node)][adjacent_node]
                    flow_entry = dict()
                    flow_entry['match']=OFPHashableMatch(in_port=inport)
                    flow_entry['inst']=[ofparser.OFPInstructionWriteMetadata(inport, 0xffffffffffffffff),
                        ofparser.OFPInstructionGotoTable(1)]
                    flow_entry['table_id']=0
                    flow_entry['priority']=100
                    flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)

        ''' STAGE 1 '''
        for node in node_dict.keys():
            # table miss for multiple faults scenarios
            flow_entry = dict()
            flow_entry['match']=OFPHashableMatch()
            flow_entry['actions']=[ofparser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
            flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
            flow_entry['table_id']=1
            flow_entry['priority']=1
            flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)

        count = 1
        for request in requests:

            print "Processing request %d/%d: %s" %(count,len(requests),request)

            primary_path = requests[request]['primary_path']

            # first primary path node: we assume a node is always a detect/det&red. Packets are always forwarded to table 2 and eventually table 3.
            # We don't try to avoid probing towards input port since we do not probe for faults of host-switch link
            #outport = ports_dict['s'+str(primary_path[0])]['s'+str(primary_path[1])]
            flow_entry = dict()
            flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=0)
            flow_entry['actions']=[ofparser.OFPActionSetField(mpls_label=16)]
            flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions']),
                ofparser.OFPInstructionGotoTable(2)]
            flow_entry['table_id']=1
            flow_entry['priority']=10
            flow_entries_dict = add_flow_entry(flow_entries_dict,primary_path[0],flow_entry)

            # intermediate primary path nodes, if any
            for node in primary_path[1:-1]:
                # if 'node' is a det or a det&red towards the inport for at least one request => we want to avoid probing towards a port from which a packet has just arrived: we reset probing timer in detect/det&red FSM associated to the inport
                for idx,t in enumerate(detection_timeouts_list):
                    flow_entry = dict()
                    flow_entry['actions'] = []
                    node_before_me_in_pp = primary_path[ primary_path.index(node)-1 ]
                    inport=ports_dict['s'+str(node)]['s'+str(node_before_me_in_pp)]
                    if is_detect_given_fault(node,(node,node_before_me_in_pp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_before_me_in_pp),node_dict,faults):
                        flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions']),
                        ofparser.OFPInstructionGotoTable(2)]
                    flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=16,**match_flow(request))
                    flow_entry['table_id']=1
                    flow_entry['priority']=10
                    if is_detect_given_fault(node,(node,node_before_me_in_pp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_before_me_in_pp),node_dict,faults):
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,node,flow_entry,t)
                        if idx==0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                    else:
                        # if the SetState action is not present => there's no timeout in this entry => just install it in the main dict
                        flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                        break

            # last primary path node is primary_path[-1]

            for idx,t in enumerate(detection_timeouts_list):
                flow_entry = dict()
                flow_entry['actions'] = []
                node_before_me_in_pp = primary_path[-2]
                inport=ports_dict['s'+str(primary_path[-1])]['s'+str(node_before_me_in_pp)]
                # if 'node' is a det or a det&red towards the inport for at least one request => we want to avoid probing towards a port from which a packet has just arrived: we reset probing timer in detect/det&red FSM associated to the inport
                if is_detect_given_fault(primary_path[-1],(primary_path[-1],node_before_me_in_pp),node_dict,faults) or is_detect_redirect_given_fault(primary_path[-1],(primary_path[-1],node_before_me_in_pp),node_dict,faults):
                    flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])
                # we need to match on request because a node could be an intermediate node for some requests (rule above) but a last PP node for others
                flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=16,**match_flow(request))
                flow_entry['actions'].extend([ofparser.OFPActionPopMpls(),
                    ofparser.OFPActionOutput(ports_dict['s'+str(primary_path[-1])]['h'+str(primary_path[-1])],0)])
                flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                flow_entry['table_id']=1
                flow_entry['priority']=100 # higher priority
                if is_detect_given_fault(primary_path[-1],(primary_path[-1],node_before_me_in_pp),node_dict,faults) or is_detect_redirect_given_fault(primary_path[-1],(primary_path[-1],node_before_me_in_pp),node_dict,faults):
                    flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,primary_path[-1],flow_entry,t)
                    if idx==0:
                        flow_entries_dict = add_flow_entry(flow_entries_dict,primary_path[-1],flow_entry)
                else:
                    flow_entries_dict = add_flow_entry(flow_entries_dict,primary_path[-1],flow_entry)
                    break
            
            for fault in requests[request]['faults']:

                detect_node = requests[request]['faults'][fault]['detect_node']
                redirect_node = requests[request]['faults'][fault]['redirect_node']

                fw_back_path = requests[request]['faults'][fault]['fw_back_path']
                if fw_back_path!=None:
                    # internal forward back nodes (not including the detect only and the redirect only)
                    for node in fw_back_path[1:-1]:
                        # probe packets DOWN->UP coming from the source are forwarded on the PP => we need to match on the request (to get the PP) and on the input port (to get the direction)
                        for idx,t in enumerate(detection_timeouts_list):
                            flow_entry = dict()
                            flow_entry['actions'] = []
                            node_before_me_in_fwbp = fw_back_path[ fw_back_path.index(node)-1 ]
                            inport=ports_dict['s'+str(node)]['s'+str(node_before_me_in_fwbp)]
                            # if 'node' is a det or a det&red towards the inport for at least one request => we want to avoid probing towards a port from which a packet has just arrived: we reset probing timer in detect/det&red FSM associated to the inport
                            if is_detect_given_fault(node,(node,node_before_me_in_fwbp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_before_me_in_fwbp),node_dict,faults):
                                flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])

                            node_after_me_in_fwbp = fw_back_path[ fw_back_path.index(node)+1 ]
                            outport=ports_dict['s'+str(node)]['s'+str(node_after_me_in_fwbp)]
                            flow_entry['match']=OFPHashableMatch(in_port=inport, eth_type=0x8847, mpls_label=probe_down_to_up_tag(fault,fault_ID),**match_flow(request))
                            flow_entry['actions'].extend([ofparser.OFPActionOutput(outport)])
                            flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                            flow_entry['table_id']=1
                            flow_entry['priority']=10
                            if is_detect_given_fault(node,(node,node_before_me_in_fwbp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_before_me_in_fwbp),node_dict,faults):
                                flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,node,flow_entry,t)
                                if idx==0:
                                    flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                            else:
                                flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                                break

                        # probe packets DOWN->UP coming from the fault are forwarded on the PP => we need to match on the request (to get the PP) and on the input port (to get the direction)
                        for idx,t in enumerate(detection_timeouts_list):
                            flow_entry = dict()
                            flow_entry['actions'] = []
                            node_after_me_in_fwbp = fw_back_path[ fw_back_path.index(node)+1 ]
                            inport=ports_dict['s'+str(node)]['s'+str(node_after_me_in_fwbp)]
                            # if 'node' is a det or a det&red towards the inport for at least one request => we want to avoid probing towards a port from which a packet has just arrived: we reset probing timer in detect/det&red FSM associated to the inport
                            if is_detect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults):
                                flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])

                            node_before_me_in_fwbp = fw_back_path[ fw_back_path.index(node)-1 ]
                            outport=ports_dict['s'+str(node)]['s'+str(node_before_me_in_fwbp)]
                            flow_entry['match']=OFPHashableMatch(in_port=inport, eth_type=0x8847, mpls_label=probe_down_to_up_tag(fault,fault_ID),**match_flow(request))
                            flow_entry['actions'].extend([ofparser.OFPActionOutput(outport)])
                            flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                            flow_entry['table_id']=1
                            flow_entry['priority']=10
                            if is_detect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults):
                                flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,node,flow_entry,t)
                                if idx==0:
                                    flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                            else:
                                flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                                break

                        # fault-tagged packets coming from the fault are forwarded on the PP => we need to match on the request (to get the PP, since the same tag is shared by many requests involved in the same fault)
                        for idx,t in enumerate(detection_timeouts_list):
                            flow_entry = dict()
                            flow_entry['actions'] = []
                            node_after_me_in_fwbp = fw_back_path[ fw_back_path.index(node)+1 ]
                            inport=ports_dict['s'+str(node)]['s'+str(node_after_me_in_fwbp)]
                            # if 'node' is a det or a det&red towards the inport for at least one request => we want to avoid probing towards a port from which a packet has just arrived: we reset probing timer in detect/det&red FSM associated to the inport
                            if is_detect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults):
                                flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])

                            node_before_me_in_fwbp = fw_back_path[ fw_back_path.index(node)-1 ]
                            outport=ports_dict['s'+str(node)]['s'+str(node_before_me_in_fwbp)]
                            flow_entry['match']=OFPHashableMatch(eth_type=0x8847, mpls_label=fault_tag(faults,fault,fault_ID),global_state=osparser.masked_global_state_from_str("1",outport-1),**match_flow(request))
                            flow_entry['actions'].extend([ofparser.OFPActionOutput(outport)])
                            flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                            flow_entry['table_id']=1
                            flow_entry['priority']=10
                            if is_detect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults) or is_detect_redirect_given_fault(node,(node,node_after_me_in_fwbp),node_dict,faults):
                                flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,node,flow_entry,t)
                                if idx==0:
                                    flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                            else:
                                flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)
                                break

                detour_path = requests[request]['faults'][fault]['detour_path']
                # internal detour nodes (not including the two nodes lying on the PP)
                for detour_node in detour_path[1:-1]:
                    # fault-tagged data packets coming from the source are forwarded on the DETOUR 
                    # => we need to match on the request (to get the DETOUR, since the same tag is shared by many requests involved in the same fault, maybe having different detour)
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        flow_entry['actions'] = []
                        detour_node_before_me_in_detour = detour_path[ detour_path.index(detour_node)-1 ]
                        inport=ports_dict['s'+str(detour_node)]['s'+str(detour_node_before_me_in_detour)]
                        # if 'detour_node' is a det or a det&red towards the inport for at least one request => we want to avoid probing towards a port from which a packet has just arrived: we reset probing timer in detect/det&red FSM associated to the inport
                        if is_detect_given_fault(detour_node,(detour_node,detour_node_before_me_in_detour),node_dict,faults) or is_detect_redirect_given_fault(detour_node,(detour_node,detour_node_before_me_in_detour),node_dict,faults):
                            flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])

                        detour_node_after_me_in_detour = detour_path[ detour_path.index(detour_node)+1 ]
                        outport=ports_dict['s'+str(detour_node)]['s'+str(detour_node_after_me_in_detour)]
                        flow_entry['match']=OFPHashableMatch(eth_type=0x8847, mpls_label=fault_tag(faults,fault,fault_ID), global_state=osparser.masked_global_state_from_str("1",outport-1),**match_flow(request))
                        flow_entry['actions'].extend([ofparser.OFPActionOutput(outport)])
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['table_id']=1
                        flow_entry['priority']=10
                        if is_detect_given_fault(detour_node,(detour_node,detour_node_before_me_in_detour),node_dict,faults) or is_detect_redirect_given_fault(detour_node,(detour_node,detour_node_before_me_in_detour),node_dict,faults):
                            flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detour_node,flow_entry,t)
                            if idx==0:
                                flow_entries_dict = add_flow_entry(flow_entries_dict,detour_node,flow_entry)
                        else:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detour_node,flow_entry)
                            break


                # last detour node: fault-tagged data packets are put on the PP with label 16 or sent to the host after popping the label.
                # We need to match on the request (to get the PP)
                for idx,t in enumerate(detection_timeouts_list):
                    flow_entry = dict()
                    flow_entry['actions'] = []
                    node_before_me_in_detour = detour_path[-2]
                    inport=ports_dict['s'+str(detour_path[-1])]['s'+str(node_before_me_in_detour)]
                    # if last detour node' is a detect or a detect&redirect towards that port for at least one request => we want to avoid probing towards a port from which a packet has just arrived
                    if is_detect_given_fault(detour_path[-1],(detour_path[-1],node_before_me_in_detour),node_dict,faults) or is_detect_redirect_given_fault(detour_path[-1],(detour_path[-1],node_before_me_in_detour),node_dict,faults):
                        flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])

                    if detour_path[-1]==primary_path[-1]:
                        flow_entry['actions'].extend([ofparser.OFPActionPopMpls(),
                            ofparser.OFPActionOutput(ports_dict['s'+str(detour_path[-1])]['h'+str(detour_path[-1])],0)])
                        flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=fault_tag(faults,fault,fault_ID),**match_flow(request))
                    else:
                        node_after_me_in_primary = primary_path[ primary_path.index(detour_path[-1])+1 ]
                        outport=ports_dict['s'+str(detour_path[-1])]['s'+str(node_after_me_in_primary)]
                        flow_entry['actions'].extend([ofparser.OFPActionSetField(mpls_label=16),
                            ofparser.OFPActionOutput(outport,0)])
                        # In theory if I'm coming from the detour, I'm already in fault conditions => Under single failure assumption packets are fwd on the primary path without checking the state of subsequent links... (eventually we could go to table 2 if we wanted to handle some multiple lucky disjoint failures scenarios). [see node after detect]
                        flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=fault_tag(faults,fault,fault_ID),**match_flow(request))
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['table_id']=1
                    flow_entry['priority']=10
                    if is_detect_given_fault(detour_path[-1],(detour_path[-1],node_before_me_in_detour),node_dict,faults) or is_detect_redirect_given_fault(detour_path[-1],(detour_path[-1],node_before_me_in_detour),node_dict,faults):
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detour_path[-1],flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detour_path[-1],flow_entry)
                    else:
                        flow_entries_dict = add_flow_entry(flow_entries_dict,detour_path[-1],flow_entry)
                        break

                if detect_node!=redirect_node:

                    # detect only node
                    # HB reply packets (probe packets UP->DOWN) received from the subsequent node are dropped
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        node_after_detect = primary_path[ primary_path.index(detect_node)+1 ]
                        inport = ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]
                        flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=HB_reply_tag(faults))
                        (global_state, global_state_mask) = osparser.masked_global_state_from_str("1",ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]-1)
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state()),
                                                   osparser.OFPExpActionSetGlobalState(global_state, global_state_mask)]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['table_id']=1
                        flow_entry['priority']=10
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                    # detect only node
                    # probe packets DOWN->UP received from the subsequent node are sent back towards the relative redirect only 
                    # => we need to match on the request (to get the PP) and on the input port (to get the direction).
                    # match on request is mandatory since this node could be a detect only for a request but also a det&red for another (the probe_down_to_up tag would be the same, it's related to the adjacent node!)
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        node_after_detect = primary_path[ primary_path.index(detect_node)+1 ]
                        node_before_detect = primary_path[ primary_path.index(detect_node)-1 ]
                        inport = ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]
                        flow_entry['match']=OFPHashableMatch(in_port=inport,eth_type=0x8847,mpls_label=probe_down_to_up_tag(fault,fault_ID),**match_flow(request))
                        (global_state, global_state_mask) = osparser.masked_global_state_from_str("1",ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]-1)
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state()), 
                                                   ofparser.OFPActionOutput(ports_dict['s'+str(detect_node)]['s'+str(node_before_detect)]),
                                                   osparser.OFPExpActionSetGlobalState(global_state, global_state_mask)]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['table_id']=1
                        flow_entry['priority']=10
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                    # detect only node
                    # probe packets DOWN->UP received from the redirect only node are sent to the node after detect
                    # => we need to match on the request (to get the PP and the outport) and on the input port (to get the direction).
                    # TODO Shall we perform here the usual check to avoid probing towards the input port?!?
                    flow_entry = dict()
                    node_before_detect = primary_path[ primary_path.index(detect_node)-1 ]
                    node_after_detect = primary_path[ primary_path.index(detect_node)+1 ]
                    outport=ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]
                    inport = ports_dict['s'+str(detect_node)]['s'+str(node_before_detect)]
                    flow_entry['match']=OFPHashableMatch(in_port=inport,eth_type=0x8847,mpls_label=probe_down_to_up_tag(fault,fault_ID),**match_flow(request))
                    flow_entry['actions']=[ofparser.OFPActionOutput(ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['table_id']=1
                    flow_entry['priority']=10
                    flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                    # redirect only node
                    # probe packets DOWN->UP received back from the detect only node are dropped (switch back to the primary path).
                    # We do not need to match on request since the update of FSM in stage 2 will be performed with update-scope=MAC,MAC automagically"
                    # TODO Shall we perform here the usual check to avoid probing towards the input port?!?
                    for idx,t in enumerate(flowlet_timeouts_list):
                        flow_entry = dict()
                        node_after_redirect = primary_path[ primary_path.index(redirect_node)+1 ]
                        inport = ports_dict['s'+str(redirect_node)]['s'+str(node_after_redirect)]
                        flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=probe_down_to_up_tag(fault,fault_ID),in_port=inport,**match_flow(request))
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=fault_resolved_state(faults,fault,fault_ID), table_id=2, idle_timeout=delta3(t), idle_rollback=0, hard_timeout=delta4(t), hard_rollback=0)]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['priority']=10
                        flow_entry['table_id']=1
                        flow_entries_with_flowlet_timeouts_dict = add_flowlet_timeout_entry(flow_entries_with_flowlet_timeouts_dict,redirect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                    # redirect only node
                    # fault-tagged data packets received back from the detect only node are sent to table 2
                    # => we need to match on request to get the PP and check if this node is hte redirect for this request, since the same tag is shared by multiple requests
                    # TODO Shall we perform here the usual check to avoid probing towards the input port?!?
                    flow_entry = dict()
                    node_after_redirect = primary_path[ primary_path.index(redirect_node)+1 ]
                    inport = ports_dict['s'+str(redirect_node)]['s'+str(node_after_redirect)]
                    flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=fault_tag(faults,fault,fault_ID),**match_flow(request))
                    flow_entry['inst'] = [ofparser.OFPInstructionGotoTable(2)]
                    flow_entry['table_id']=1
                    flow_entry['priority']=10
                    flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                else:
                    # detect&redirect node
                    # HB reply packets (probe packets UP->DOWN) received from the subsequent node are dropped
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        node_after_detect = primary_path[ primary_path.index(detect_node)+1 ]
                        inport = ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]
                        flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=HB_reply_tag(faults))
                        (global_state, global_state_mask) = osparser.masked_global_state_from_str("1",ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]-1)
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state()),
                                                   osparser.OFPExpActionSetGlobalState(global_state, global_state_mask)]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['table_id'] = 1
                        flow_entry['priority'] = 10
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                    # detect&redirect node
                    # probe packets DOWN->UP received from the subsequent node are dropped
                    # => we need to match on the request (to get the PP) and on the input port (to get the direction).
                    # match on request is mandatory since this node could be a detect only for a request but also a det&red for another (the probe_down_to_up tag would be the same, it's related to the adjacent node!)
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        node_after_detect = primary_path[ primary_path.index(detect_node)+1 ]
                        inport = ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]
                        flow_entry['match']=OFPHashableMatch(in_port=inport,eth_type=0x8847,mpls_label=probe_down_to_up_tag(fault,fault_ID),**match_flow(request))
                        (global_state, global_state_mask) = osparser.masked_global_state_from_str("1",ports_dict['s'+str(detect_node)]['s'+str(node_after_detect)]-1)
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state()),
                                                   osparser.OFPExpActionSetGlobalState(global_state, global_state_mask)]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['table_id'] = 1
                        flow_entry['priority'] = 10
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                # node after detect - HB request packets (probe UP->DOWN) received from detect node are duplicated, retagged and sent backward&forward
                # => we need to match on the requests because node agter detect might be a switch attached to the host (so we need the outport instead of sending to table 2)
                node_after_detect = primary_path[ primary_path.index(detect_node)+1 ]
                for idx,t in enumerate(detection_timeouts_list):
                    flow_entry = dict()
                    flow_entry['actions'] = []
                    #inport=ports_dict['s'+str(node_after_detect)]['s'+str(detect_node)]
                    # if node after detect is a detect or a detect&redirect towards that port for at least one request => we want to avoid probing towards a port from which a packet has just arrived
                    if is_detect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults) or is_detect_redirect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults):
                        flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])
                    # probe packet is sent back to the detect...
                    flow_entry['actions'].extend([ofparser.OFPActionSetField(mpls_label=HB_reply_tag(faults)),ofparser.OFPActionOutput(ofproto.OFPP_IN_PORT)])
                    # ... but since this packet contains data we need to process it according to node_after_detect's behaviour
                    if node_after_detect==primary_path[-1]:
                        flow_entry['actions'].extend([ofparser.OFPActionPopMpls(),
                            ofparser.OFPActionOutput(ports_dict['s'+str(node_after_detect)]['h'+str(node_after_detect)],0)])
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    else:
                        flow_entry['actions'].extend([ofparser.OFPActionSetField(mpls_label=16)])
                        node_after_me_in_primary = primary_path[ primary_path.index(node_after_detect)+1 ]
                        outport=ports_dict['s'+str(node_after_detect)]['s'+str(node_after_me_in_primary)]
                        flow_entry['inst']=[ofparser.OFPInstructionGotoTable(2),ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    
                    flow_entry['match']=OFPHashableMatch(eth_type=0x8847,mpls_label=HB_req_tag(faults),**match_flow(request))
                    flow_entry['table_id']=1
                    flow_entry['priority']=10
                    if is_detect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults) or is_detect_redirect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults):
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,node_after_detect,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,node_after_detect,flow_entry)
                    else:
                        flow_entries_dict = add_flow_entry(flow_entries_dict,node_after_detect,flow_entry)
                        break

                # node after detect - probe DOWN->UP from det&red node or redirect node are sent back
                node_after_detect = primary_path[ primary_path.index(detect_node)+1 ]
                for idx,t in enumerate(detection_timeouts_list):
                    flow_entry = dict()
                    flow_entry['actions'] = []
                    inport=ports_dict['s'+str(node_after_detect)]['s'+str(detect_node)]
                     # if node after detect is a detect or a detect&redirect towards that port for at least one request => we want to avoid probing towards a port from which a packet has just arrived
                    if is_detect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults) or is_detect_redirect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults):
                        flow_entry['actions'].extend([osparser.OFPExpActionSetState(state=UP_wait_state(), table_id=3, hard_timeout=delta6(t), hard_rollback=UP_need_HB_state())])
                    # probe packet is sent back to the detect...
                    flow_entry['actions'].extend([ofparser.OFPActionOutput(ofproto.OFPP_IN_PORT)])
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['match']=OFPHashableMatch(in_port=inport,eth_type=0x8847,mpls_label=probe_down_to_up_tag(fault,fault_ID),**match_flow(request))
                    flow_entry['table_id']=1
                    flow_entry['priority']=10
                    if is_detect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults) or is_detect_redirect_given_fault(node_after_detect,(node_after_detect,detect_node),node_dict,faults):
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,node_after_detect,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,node_after_detect,flow_entry)
                    else:
                        flow_entries_dict = add_flow_entry(flow_entries_dict,node_after_detect,flow_entry)
                        break

            count+=1

        ''' Stage 2,3,4 '''


        for node in node_dict.keys():
           # sort of table miss to forward packets to outport in case a node is not a detect for any request
           for adjacent_node in ports_dict['s'+str(node)]:
               if adjacent_node[0]=='h':
                   continue

               adjacent_node_id = int(adjacent_node[1:])

               if not is_detect_given_fault(node,(node,adjacent_node_id),node_dict,faults) and not is_detect_redirect_given_fault(node,(node,adjacent_node_id),node_dict,faults):
                   outport = ports_dict['s'+str(node)][adjacent_node]
                   flow_entry = dict()
                   flow_entry['match']=OFPHashableMatch(metadata=outport)
                   flow_entry['actions']=[ofparser.OFPActionOutput(outport)]
                   flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                   flow_entry['table_id']=3
                   flow_entry['priority']=1
                   flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)

        for request in requests:

            primary_path = requests[request]['primary_path']

            # for each PP node of the current request forwards packet to table 3 in absence of remote failure, independently from the role of this node for this request (even if it's not a redirect only)
            # we need to match on request because we need the outport to set the metadata
            # last PP node is handled in table 1
            for node in primary_path[:-1]:
                node_index_in_p_p = primary_path.index(node)
                flow_entry = dict()
                flow_entry['match']=OFPHashableMatch(state=0, eth_type=0x8847,**match_flow(request))
                flow_entry['inst']=[ofparser.OFPInstructionWriteMetadata(ports_dict['s'+str(node)]['s'+str(primary_path[node_index_in_p_p+1])], 0xffffffffffffffff),
                    ofparser.OFPInstructionGotoTable(3)]
                flow_entry['priority']=10
                flow_entry['table_id']=2
                flow_entries_dict = add_flow_entry(flow_entries_dict,node,flow_entry)

            # for each fault of the current request
            for f in (requests[request]['faults']):
                fault = requests[request]['faults'][f]
                            
                # [4] Redirect node, Detect node and Detect&Redirect node rules
                redirect_node = fault['redirect_node']
                detect_node = fault['detect_node']
                detour = fault['detour_path']

                if is_detect_given_req(detect_node,request,node_dict) or is_detect_redirect_given_req(detect_node,request,node_dict):
                    # state transitions common to detect only and detect&redirect nodes

                    node_index_in_p_p = primary_path.index(detect_node)

                    '''UP: wait: data traffic is forwarded'''
                    flow_entry = dict()
                    flow_entry['match']=OFPHashableMatch(state=UP_wait_state(), eth_type=0x8847, metadata=ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])])
                    flow_entry['actions']=[ofparser.OFPActionOutput(ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=3
                    flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                    '''UP: need heartbeat (DEF): a data packet packet is forwarded toward the next node as a probe'''
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        flow_entry['match']=OFPHashableMatch(state=UP_need_HB_state(), eth_type=0x8847, metadata=ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])])
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=UP_HB_requested_state(), table_id=3, hard_timeout=delta7(t), hard_rollback=DOWN_need_probe_state()),
                                               ofparser.OFPActionSetField(mpls_label=HB_req_tag(faults)),
                                               ofparser.OFPActionOutput(ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])])]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['priority']=10
                        flow_entry['table_id']=3
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                    '''UP: heartbeat requested: data traffic is forwarded'''
                    flow_entry = dict()
                    flow_entry['match']=OFPHashableMatch(state=UP_HB_requested_state(), eth_type=0x8847, metadata=ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])])
                    flow_entry['actions']=[ofparser.OFPActionOutput(ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=3
                    flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)


                # [4.1] Detect&Redirect node rules
                if redirect_node == detect_node:

                    node_index_in_p_p = primary_path.index(redirect_node)

                    '''DOWN: need probe: data packet is forwarded on the detour'''
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        if node_index_in_p_p == 0:
                            flow_entry['match']=OFPHashableMatch(state=DOWN_need_probe_state(), in_port=ports_dict['s'+str(redirect_node)]['h'+str(redirect_node)],eth_type=0x8847,
                                metadata=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])],**match_flow(request))
                        else:
                            flow_entry['match']=OFPHashableMatch(state=DOWN_need_probe_state(), in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p-1])],
                                eth_type=0x8847,metadata=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])],**match_flow(request))
                        
                        (global_state, global_state_mask) = osparser.masked_global_state_from_str("0",ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])]-1)
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=DOWN_probe_sent_state(), table_id=3, hard_timeout=delta5(t), hard_rollback=DOWN_need_probe_state()),
                                               ofparser.OFPActionSetField(mpls_label=fault_tag(faults,f,fault_ID)), ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(detour[1])]),
                                               ofparser.OFPActionSetField(mpls_label=probe_down_to_up_tag(f,fault_ID)), ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])]),
                                               osparser.OFPExpActionSetGlobalState(global_state, global_state_mask)]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['priority']=10
                        flow_entry['table_id']=3
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,redirect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                    '''DOWN: probe sent: data packet is forwarded on the detour'''
                    flow_entry = dict()
                    if node_index_in_p_p == 0:
                        flow_entry['match']=OFPHashableMatch(state=DOWN_probe_sent_state(), in_port=ports_dict['s'+str(redirect_node)]['h'+str(redirect_node)], 
                            eth_type=0x8847,
                            metadata=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])],**match_flow(request))
                    else:
                        flow_entry['match']=OFPHashableMatch(state=DOWN_probe_sent_state(), in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p-1])], 
                            eth_type=0x8847,
                            metadata=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])],**match_flow(request))
                    flow_entry['actions']=[ofparser.OFPActionSetField(mpls_label=fault_tag(faults,f,fault_ID)), 
                                           ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(detour[1])])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=3
                    flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)
                    
                else:
                    # [4.2] Redirect only node rules

                    node_index_in_p_p = primary_path.index(redirect_node)

                    '''Probing rule: packet duplicated in both primary and detour path'''
                    flow_entry = dict()
                    if node_index_in_p_p == 0:
                        flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['h'+str(redirect_node)], state=need_probe_state(faults,f,fault_ID),
                            eth_type=0x8847,**match_flow(request))
                    else:
                        flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p-1])], state=need_probe_state(faults,f,fault_ID),
                            eth_type=0x8847,**match_flow(request))
                    flow_entry['actions']=[ofparser.OFPActionSetField(mpls_label=fault_tag(faults,f,fault_ID)),
                                       ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(detour[1])])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=2
                    flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                    '''DEF: In case this node has also a detect or a detect&redirect behaviour for the same request, forward the packet to the correct table'''
                    if is_detect_given_req(redirect_node,request,node_dict) or is_detect_redirect_given_req(redirect_node,request,node_dict):
                        flow_entry = dict()
                        flow_entry['match']=OFPHashableMatch(state=0, eth_type=0x8847,**match_flow(request))
                        flow_entry['inst']=[ofparser.OFPInstructionWriteMetadata(ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])], 0xffffffffffffffff)]
                        if is_detect_given_req(redirect_node,request,node_dict) or is_detect_redirect_given_req(redirect_node,request,node_dict):
                            flow_entry['inst'].extend([ofparser.OFPInstructionGotoTable(3)])
                        flow_entry['priority']=10
                        flow_entry['table_id']=2
                        flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)
                    
                        '''DEF: In this case this node is just a redirect only, forward on the next primary hop'''
                        # we need to match on the request to get the outport
                    else:
                        flow_entry = dict()
                        flow_entry['match']=OFPHashableMatch(state=0, eth_type=0x8847,**match_flow(request))
                        flow_entry['actions']=[ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])])]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['priority']=10
                        flow_entry['table_id']=2
                        flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                    '''DEF->FAULT SIGNALED: switch to the burst handling state'''
                    for idx,t in enumerate(flowlet_timeouts_list):
                        flow_entry = dict()
                        flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])], state=0,
                            eth_type=0x8847, mpls_label=fault_tag(faults,f,fault_ID),**match_flow(request))
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=fault_signaled_state(faults,f,fault_ID), table_id=2, idle_timeout=delta1(t), idle_rollback=detour_enabled_state(f,fault_ID),hard_timeout=delta2(t), hard_rollback=detour_enabled_state(f,fault_ID)),
                                               ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(detour[1])])]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['priority']=100
                        flow_entry['table_id']=2
                        flow_entries_with_flowlet_timeouts_dict = add_flowlet_timeout_entry(flow_entries_with_flowlet_timeouts_dict,redirect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                    '''FAULT SIGNALED: packet of the current burst should be sent to the primary path'''
                    flow_entry = dict()
                    if node_index_in_p_p == 0:
                        flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['h'+str(redirect_node)], state=fault_signaled_state(faults,f,fault_ID),
                            eth_type=0x8847,**match_flow(request))
                    else:
                        flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p-1])], state=fault_signaled_state(faults,f,fault_ID),
                            eth_type=0x8847,**match_flow(request))
                    flow_entry['actions']=[ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=2
                    flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                    '''FAULT SIGNALED: tagged packet of the current burst should be sent to the detour path'''
                    flow_entry = dict()
                    flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])], state=fault_signaled_state(faults,f,fault_ID),
                        eth_type=0x8847, **match_flow(request))
                    flow_entry['actions']=[ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(detour[1])])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=2
                    flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)
                    
                    '''FAULT RESOLVED->DEF: packet of the current burst should be sent to the detour path'''
                    flow_entry = dict()
                    if node_index_in_p_p == 0:
                        flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['h'+str(redirect_node)], state=fault_resolved_state(faults,f,fault_ID),
                            eth_type=0x8847, **match_flow(request))
                    else:
                        flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p-1])], state=fault_resolved_state(faults,f,fault_ID),
                            eth_type=0x8847, **match_flow(request))
                    flow_entry['actions']=[ofparser.OFPActionSetField(mpls_label=fault_tag(faults,f,fault_ID)),
                                           ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(detour[1])])]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=2
                    flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)

                    '''DETOUR ENABLED: each new packet is forwarded to the detour path'''
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        if node_index_in_p_p == 0:
                            flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['h'+str(redirect_node)], state=detour_enabled_state(f,fault_ID),
                                eth_type=0x8847, **match_flow(request))
                        else:
                            flow_entry['match']=OFPHashableMatch(in_port=ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p-1])], state=detour_enabled_state(f,fault_ID),
                                eth_type=0x8847, **match_flow(request))
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=need_probe_state(faults,f,fault_ID), table_id=2, hard_timeout=delta5(t), hard_rollback=detour_enabled_state(f,fault_ID)),
                                                   ofparser.OFPActionSetField(mpls_label=fault_tag(faults,f,fault_ID)), ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(detour[1])]),
                                                   ofparser.OFPActionSetField(mpls_label=probe_down_to_up_tag(f,fault_ID)), ofparser.OFPActionOutput(ports_dict['s'+str(redirect_node)]['s'+str(primary_path[node_index_in_p_p+1])])]

                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['priority']=10
                        flow_entry['table_id']=2
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,redirect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,redirect_node,flow_entry)  

                    # [4.3] Detect only node rules
                    
                    node_index_in_p_p = primary_path.index(detect_node)

                    '''DOWN: need probe: data packet is forwarded on the detour'''
                    for idx,t in enumerate(detection_timeouts_list):
                        flow_entry = dict()
                        flow_entry['match']=OFPHashableMatch(state=DOWN_need_probe_state(), in_port=ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p-1])],
                            eth_type=0x8847,
                            metadata=ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])],**match_flow(request))
                        (global_state, global_state_mask) = osparser.masked_global_state_from_str("0",ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])]-1)
                        flow_entry['actions']=[osparser.OFPExpActionSetState(state=DOWN_probe_sent_state(), table_id=3, hard_timeout=delta5(t), hard_rollback=DOWN_need_probe_state()),
                                               ofparser.OFPActionSetField(mpls_label=fault_tag(faults,f,fault_ID)), ofparser.OFPActionOutput(ofproto.OFPP_IN_PORT),
                                               ofparser.OFPActionSetField(mpls_label=HB_req_tag(faults)), ofparser.OFPActionOutput(ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])]),
                                               osparser.OFPExpActionSetGlobalState(global_state, global_state_mask)]
                        flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                        flow_entry['priority']=10
                        flow_entry['table_id']=3
                        flow_entries_with_detection_timeouts_dict = add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict,detect_node,flow_entry,t)
                        if idx == 0:
                            flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

                    '''DOWN: probe sent: data packet is forwarded on the detour'''
                    flow_entry = dict()
                    flow_entry['match']=OFPHashableMatch(state=DOWN_probe_sent_state(), in_port=ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p-1])], 
                        eth_type=0x8847,
                        metadata=ports_dict['s'+str(detect_node)]['s'+str(primary_path[node_index_in_p_p+1])],**match_flow(request))
                    flow_entry['actions']=[ofparser.OFPActionSetField(mpls_label=fault_tag(faults,f,fault_ID)), 
                                           ofparser.OFPActionOutput(ofproto.OFPP_IN_PORT)]
                    flow_entry['inst']=[ofparser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, flow_entry['actions'])]
                    flow_entry['priority']=10
                    flow_entry['table_id']=3
                    flow_entries_dict = add_flow_entry(flow_entries_dict,detect_node,flow_entry)

        if check_cache:
            with open('./tmp/' + results_hash + '-flow_entries.p', 'wb') as fp:
                pickle.dump(flow_entries_dict, fp)
            with open('./tmp/' + results_hash + '-flow_stats.p', 'wb') as fp:
                pickle.dump(flow_stats_dict, fp)
            with open('./tmp/' + results_hash + '-timeout.p', 'wb') as fp:
                pickle.dump(flow_entries_with_detection_timeouts_dict, fp)
            with open('./tmp/' + results_hash + '-burst.p', 'wb') as fp:
                pickle.dump(flow_entries_with_flowlet_timeouts_dict, fp)

    if dpctl_script:
        create_dpctl_script(fault_ID,faults)

    return (fault_ID,flow_entries_dict,flow_entries_with_detection_timeouts_dict, flow_entries_with_flowlet_timeouts_dict)

def get_flow_stats_dict(flow_entries_dict):
    flow_stats_dict = {}

    flow_stats_dict['global'] = {}
    flow_stats_dict['global']['tot_flows'] = 0
    for table_id in range(5):
        flow_stats_dict['global'][table_id] = 0

    for datapath_id in flow_entries_dict:
        flow_stats_dict[datapath_id] = {}
        flow_stats_dict[datapath_id]['tot_flows'] = 0
        for table_id in range(5):
            flow_stats_dict[datapath_id][table_id] = 0
        
        for table_id in flow_entries_dict[datapath_id]:
            flow_stats_dict[datapath_id][table_id] = len(flow_entries_dict[datapath_id][table_id])
            flow_stats_dict[datapath_id]['tot_flows'] += len(flow_entries_dict[datapath_id][table_id])
            flow_stats_dict['global'][table_id] += len(flow_entries_dict[datapath_id][table_id])
            flow_stats_dict['global']['tot_flows'] += len(flow_entries_dict[datapath_id][table_id])

    return flow_stats_dict

def print_flow_stats(flow_stats_dict):

    for nodes in flow_stats_dict:
        if nodes!='global':
            print("\nNODE "+str(nodes)+": ")
            for rule_type in flow_stats_dict[nodes]:
                if str(rule_type)!='tot_flows':
                    s="Table "+str(rule_type)+"="+str(flow_stats_dict[nodes][rule_type])
                    s=s.ljust(16)
                    s+="\t("
                    s+="%.2f" % (flow_stats_dict[nodes][rule_type]*100/flow_stats_dict[nodes]['tot_flows'])
                    s+="%)"
                    print(s)
            print("-->TOT FLOWS="+str(flow_stats_dict[nodes]['tot_flows']))
    print("----------------------------------")
    print("GLOBAL COUNTERS\n")
    for rule_type in flow_stats_dict['global']:
        if str(rule_type)!='tot_flows':
            s="Table "+str(rule_type)+"="+str(flow_stats_dict['global'][rule_type])
            s=s.ljust(16)
            s+="\t("
            s+="%.2f" % (flow_stats_dict['global'][rule_type]*100/flow_stats_dict['global']['tot_flows'])
            s+="%)"
            print(s)
    print("-->TOT FLOWS="+str(flow_stats_dict['global']['tot_flows']))

def add_flow_entry(flow_entries_dict,datapath_id,flow_entry):    
    if not datapath_id in flow_entries_dict:
        flow_entries_dict[datapath_id] = {}
    if not flow_entry['table_id'] in flow_entries_dict[datapath_id]:
        flow_entries_dict[datapath_id][ flow_entry['table_id'] ] = {}
 
    flow_entries_dict[datapath_id][ flow_entry['table_id'] ][ flow_entry['match'] ] = {'inst': flow_entry['inst'], 'priority': flow_entry['priority']}

    return flow_entries_dict

def add_detection_timeout_entry(flow_entries_with_detection_timeouts_dict, datapath_id, flow_entry, timeout):
    if not timeout in flow_entries_with_detection_timeouts_dict:
        flow_entries_with_detection_timeouts_dict[timeout] = {}
    if not datapath_id in flow_entries_with_detection_timeouts_dict[timeout]:
        flow_entries_with_detection_timeouts_dict[timeout][datapath_id] = {}
    if not flow_entry['table_id'] in flow_entries_with_detection_timeouts_dict[timeout][datapath_id]:
        flow_entries_with_detection_timeouts_dict[timeout][datapath_id][ flow_entry['table_id'] ] = {}
    flow_entries_with_detection_timeouts_dict[timeout][datapath_id][ flow_entry['table_id'] ][ flow_entry['match'] ] = {'inst': flow_entry['inst'], 'priority': flow_entry['priority']}

    return flow_entries_with_detection_timeouts_dict

def add_flowlet_timeout_entry(flow_entries_with_flowlet_timeouts_dict, datapath_id, flow_entry, timeout):
    if not timeout in flow_entries_with_flowlet_timeouts_dict:
        flow_entries_with_flowlet_timeouts_dict[timeout] = {}
    if not datapath_id in flow_entries_with_flowlet_timeouts_dict[timeout]:
        flow_entries_with_flowlet_timeouts_dict[timeout][datapath_id] = {}
    if not flow_entry['table_id'] in flow_entries_with_flowlet_timeouts_dict[timeout][datapath_id]:
        flow_entries_with_flowlet_timeouts_dict[timeout][datapath_id][ flow_entry['table_id'] ] = {}
    flow_entries_with_flowlet_timeouts_dict[timeout][datapath_id][ flow_entry['table_id'] ][ flow_entry['match'] ] = {'inst': flow_entry['inst'], 'priority': flow_entry['priority']}

    return flow_entries_with_flowlet_timeouts_dict

def draw_fault_scenario(G, pos, ports_dict, title, fault_edge, pp, dp, fwp):
    nx.draw(G, pos, node_size=300, font_size=10, node_color='w', alpha=1, with_labels=True)

    if title is not None:
        plt.text(0.5, 0.5, title, fontsize=12)

    if pp is not None:
        draw_edge_node(G, pos, ports_dict, pp, 0.8, 'b')
        # Source
        nx.draw_networkx_nodes(G, pos,
                               nodelist=[pp[0]],
                               node_color='black',
                               node_size=500,
                               label='S',
                               font_size=10,
                               node_shape='s',
                               alpha=0.5)
        link_to_port={}
        for edge in G.edges():
            link_to_port[(edge[0],edge[1])]=ports_dict['s'+str(edge[0])]['s'+str(edge[1])]
            link_to_port[(edge[1],edge[0])]=ports_dict['s'+str(edge[1])]['s'+str(edge[0])]
        nx.draw_networkx_edge_labels(G, pos, font_color='#B0B0B0', edge_labels=link_to_port, font_size=8,label_pos=0.7)
        link_to_port={}
        pp_edges = [(pp[i], pp[i + 1]) for i in range(len(pp) - 1)]
        for edge in pp_edges:
            link_to_port[(edge[0],edge[1])]=ports_dict['s'+str(edge[0])]['s'+str(edge[1])]
            link_to_port[(edge[1],edge[0])]=ports_dict['s'+str(edge[1])]['s'+str(edge[0])]
        nx.draw_networkx_edge_labels(G, pos, font_color='blue', edge_labels=link_to_port, font_size=8,label_pos=0.7)


    # Detour path
    if dp is not None:
        draw_edge_node(G, pos, ports_dict, dp, 0.8, 'g')


    # Fault edge
    if fault_edge is not None:
        nx.draw_networkx_edges(G, pos,
                               edgelist=[fault_edge],
                               width=4, alpha=0.8,
                               edge_color='r')
        link_to_port={}
        for edge in [fault_edge]:
            link_to_port[(edge[0],edge[1])]=ports_dict['s'+str(edge[0])]['s'+str(edge[1])]
            link_to_port[(edge[1],edge[0])]=ports_dict['s'+str(edge[1])]['s'+str(edge[0])]
        nx.draw_networkx_edge_labels(G, pos, font_color='r', edge_labels=link_to_port, font_size=8,label_pos=0.7)

    # FW Back path
    if fwp is not None:
        draw_edge_node(G, pos, ports_dict, fwp, 0.8, 'y', 'dashed')

def draw_requests(G,pos,ports_dict,requests,faults,fault_ID,pp_edge=None, show=False):

    if pp_edge == None:
        for aedge in requests:
            draw_requests(G,pos,ports_dict,requests,faults,fault_ID,aedge, show)
        return

    areq = requests[pp_edge]

    s = 'r-' + str(pp_edge[0]) + '-' + str(pp_edge[1])
    draw_fault_scenario(G, pos, ports_dict, title='req (' + str(pp_edge[0]) + ',' + str(pp_edge[1]) + ')', pp=areq['primary_path'], dp=None, fwp=None, fault_edge=None)

    print "Drawing request", pp_edge

    if show:
        plt.show()
    else:
        plt.savefig('./figs/' + s + '.png', format="PNG", transparent=True)
    plt.clf()

    for f_edge in areq['faults']:
        fault = areq['faults'][f_edge]

        s = 'r-' + str(pp_edge[0]) + '-' + str(pp_edge[1]) + '-f-' + str(
            f_edge[0]) + '-' + str(f_edge[1])
        title = 'req (' + str(pp_edge[0]) + ',' + str(pp_edge[1]) + ')\nfault (' + str(f_edge[0]) + ',' + str(f_edge[1]) + ')\nHB request = ' + str(HB_req_tag(faults)) + '\nProbe DOWN->UP = ' + str(probe_down_to_up_tag(f_edge,fault_ID))

        draw_fault_scenario(G, pos, ports_dict, title=title, pp=areq['primary_path'], dp=fault[
                            'detour_path'], fwp=fault['fw_back_path'], fault_edge=f_edge)

        print "Drawing request", pp_edge, "with fault", f_edge

        if show:
            plt.show()
        else:
            plt.savefig('./figs/' + s + '.png', format="PNG", transparent=True)
        plt.clf()

def draw_edge_node(G, pos, ports_dict, nodes, alpha, color, style='solid'):
    nx.draw_networkx_nodes(G, pos,
                           nodelist=nodes,
                           node_color=color,
                           node_size=300,
                           font_size=10,
                           alpha=alpha)
    edges = [(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]
    nx.draw_networkx_edges(G, pos,
                           edgelist=edges,
                           width=4, alpha=alpha,
                           edge_color=color, style=style)
    link_to_port={}
    for edge in edges:
        link_to_port[(edge[0],edge[1])]=ports_dict['s'+str(edge[0])]['s'+str(edge[1])]
        link_to_port[(edge[1],edge[0])]=ports_dict['s'+str(edge[1])]['s'+str(edge[0])]
    nx.draw_networkx_edge_labels(G, pos, font_color=color, edge_labels=link_to_port, font_size=8,label_pos=0.7)

# given an int, it returns "xx:xx:xx:xx:xx:xx" string
def int_to_mac_str(host_number):
    mac_str = "{0:0{1}x}".format(int(host_number),12) # converts to hex with zero pad to 48bit
    return ':'.join(mac_str[i:i+2] for i in range(0, len(mac_str), 2)) # adds ':'

# given an int, it returns "10.x.x.x" string
def int_to_ip_str(host_number):
    ip = (10<<24) + int(host_number)
    return ".".join(map(lambda n: str(ip>>n & 0xFF), [24,16,8,0]))

'''
fault_ID dict associates each fault to a progressive number starting from 17 to 17+len(faults)-1.
fault_IDs are used for MPLS tags and flow states during failure conditions.
We need an ID also for intermediate conditions (states) between DEF and DETOUR ENABLED.
States and tags are assigned as follows:

        DE  FS  FR  PS  HB_req  HB_reply
Fault1  17  22  27  32  37      38
Fault2  18  23  28  33
...
Fault5  21  26  31  36

The following methods returns the correct ID given a fault '''
def detour_enabled_state(fault,fault_ID):
    return fault_ID[fault]
def fault_signaled_state(faults,fault,fault_ID):
    return fault_ID[fault]+len(faults)
def fault_resolved_state(faults,fault,fault_ID):
    return fault_ID[fault]+2*len(faults)
def need_probe_state(faults,fault,fault_ID):
    return fault_ID[fault]+3*len(faults)

def fault_tag(faults,fault,fault_ID):
    return need_probe_state(faults,fault,fault_ID)
def probe_down_to_up_tag(fault,fault_ID):
    return detour_enabled_state(fault,fault_ID)
def HB_req_tag(faults):
    return 17+4*len(faults)
def HB_reply_tag(faults):
    return 18+4*len(faults)

''' LF FSM states'''

def UP_need_HB_state():
    return 0
def UP_HB_requested_state():
    return 1
def DOWN_need_probe_state():
    return 2
def DOWN_probe_sent_state():
    return 3
def UP_wait_state():
    return 4

# creates a bash script that replace numeric states with labels in dpctl output
def create_dpctl_script(fault_ID,faults):
    def sed_string(state,string):
         return "sed 's/state\\x1b\\[0m=\\\""+str(state)+"\\\"/state\\x1b\\[0m=\\\""+string+"\\\"/'"

    filename='/home/mininet/dpctl-states-with-names.sh'
    f=open(filename,'w')
    f.write('if [ "$#" -ne 1 ]; then\n')
    f.write('    echo "TCP port missing!"\n')
    f.write('    echo "Usage: $0 tcp_port"\n')
    f.write('    exit\n')
    f.write('fi')

    s='watch -n0.5 --color "dpctl tcp:127.0.0.1:$1 stats-state -c'

    s=s+' | '+sed_string(0, 'DEF')
    s=s+' | '+sed_string(UP_wait_state(), 'UP: wait')
    s=s+' | '+sed_string(UP_HB_requested_state(), 'UP: HB requested')
    s=s+' | '+sed_string(DOWN_need_probe_state(), 'DOWN: need probe')
    s=s+' | '+sed_string(DOWN_probe_sent_state(), 'DOWN: probe sent')

    for fault in faults:
        s=s+' | '+sed_string(detour_enabled_state(fault,fault_ID), 'DETOUR ENABLED '+str(fault))
        s=s+' | '+sed_string(need_probe_state(faults,fault,fault_ID), 'NEED PROBE'+str(fault))
        s=s+' | '+sed_string(fault_signaled_state(faults,fault,fault_ID), 'FAULT SIGNALED '+str(fault))
        s=s+' | '+sed_string(fault_resolved_state(faults,fault,fault_ID), 'FAULT RESOLVED '+str(fault))
        s=s+' | '+sed_string(HB_req_tag(faults), 'HB '+str(fault))

    s=s+" | sed 's/metadata=\\\"0x/outport=\\\"0x/' | sed 's/metadata=\\\"\*/outport=\\\"\*/' \""
    f.write('\n'+s+'\n')
    f.close()

    os.system("chown mininet:mininet "+filename)
    os.system("chmod +x "+filename)
    print("dpctl script created: \x1B[32m"+filename+ "\x1B[0m")

check_create_tmp_dir()

'''
if __name__ == "__main__":
    generate_flow_entries_dict()

'''