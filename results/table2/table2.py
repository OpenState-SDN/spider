import networkx as nx
from dummy import execute_instance 
import sys
from fc_lib import cost_func_inv
import multiprocessing as mp
import os
import cProfile
from ryu.base import app_manager

topology_dir="/home/mininet/spider/src"
sys.path.append(os.path.abspath("/home/mininet/spider/src"))
import SPIDER_parser as f_t_parser

# Check root privileges
if os.geteuid() != 0:
	exit("You need to have root privileges to run this script")

def create_square_network(N, link_capacity=10, demand_volume=1):
	'''
	Function: create_square_network
	Summary: Create a NxN square grid network along with traffic demands between each pair of edge nodes
	Examples: With N=3, demands generated only between edge nodes (0,1,2,3,5,6,7,8)
		0--1--2
		|  |  |
		3--4--5
		|  |  |
		6--7--8
	Attributes: 
		@param (N): Number of nodes per row/column
		@param (link_capacity) default=10: link capacity value to assign to each link
		@param (demand_volume) default=1: traffic volume for each generated demand
	Returns: The networkx graph G, a demands dictionary indexed like "(src_node, dst_node) = volume"
	'''
	G = nx.Graph()
	G.add_nodes_from(range(N*N))
	ebunch = [(i,i-1) for i in range(N*N) if i%N > 0] + [(i,i-N) for i in range(N,N*N)] 
	G.add_edges_from(ebunch, capacity=link_capacity)
	st_nodes = [i for i in range(N*N) if i < N or i > (N*(N-1)-1) or i % N in (0,N-1)]
	demands = {(i,j): demand_volume for i in st_nodes for j in st_nodes if i != j}
	return G.to_directed(), demands

def create_requests_faults_dict(pps, bps):
	'''
	Given
	
	pps = {(x,y): [x, ... , y], ...}
	bps = {(x,y): {(a,b): [x, ... , y], (b,c): [x, ... , y]}, ... }

	it returns

	requests = {(x,y): {'primary_path': [...], 'faults': {(a,b): {'detour_path': [...], 'redirect_node': 7, 'fw_back_path': [...], 'detect_node': 3}}, 'pp_edge': (7, 4)}, ... }
	faults = {(a,b): {'requests': {(x,y): {'primary_path': [...], 'detour_path': [...], 'redirect_node': 2, 'fw_back_path': None, 'detect_node': 2}}}, }
	'''
	
	requests=dict()
	for req in pps:
		requests[req] = {}
		requests[req]['primary_path'] = pps[req]
		requests[req]['faults'] = {}
		if req in bps:
			for flt in bps[req]:
				# NB bps dict is indexed by 'ordered' couple of nodes (a,b), so (a,b) is different from (b,a)
				# Instead faults dict is indexed by couple of nodes (a,b) where a is always < b, so keys (a,b) with b<a cannot exist
				f_key = flt
				if flt[0]>flt[1]:
					f_key=(flt[1],flt[0])
				requests[req]['faults'][f_key] = {}
				requests[req]['faults'][f_key]['detect_node'] = flt[0]
				requests[req]['faults'][f_key]['fw_back_path'] = None

				detour=list(bps[req][flt])
				# NB detour is a list of nodes including the redirect and the last detour node, while bps is the entire E2E backup path.
				# We need to remove the beginning part common to both primary and backup path and the common part starting from the end.... 
				for node in bps[req][flt]:
					if node in pps[req]:
						detour.pop(0)
					else:
						break

				for node in reversed(bps[req][flt]):
					if node in pps[req]:
						detour.pop(-1)
					else:
						break
				# ...but we need also to add the redirect node and the last detour node
				requests[req]['faults'][f_key]['redirect_node'] = bps[req][flt][ bps[req][flt].index(detour[0])-1 ]
				requests[req]['faults'][f_key]['detour_path'] = detour
				requests[req]['faults'][f_key]['detour_path'].insert(0,requests[req]['faults'][f_key]['redirect_node'])
				requests[req]['faults'][f_key]['detour_path'].append(bps[req][flt][ bps[req][flt].index(detour[-1])+1 ])

				detect_idx = pps[req].index(requests[req]['faults'][f_key]['detect_node'])
				redirect_idx = pps[req].index(requests[req]['faults'][f_key]['redirect_node'])
				if detect_idx - redirect_idx > 1:
					requests[req]['faults'][f_key]['fw_back_path'] = pps[req][redirect_idx+1:detect_idx]

	faults=dict()
	for r in requests:
		for f in requests[r]['faults']:
			if f not in faults:
				faults[f] = {}
				faults[f]['requests'] = {}
			faults[f]['requests'][r] = {}
			faults[f]['requests'][r]['primary_path'] = requests[r]['primary_path']
			faults[f]['requests'][r]['detour_path'] = requests[r]['faults'][f]['detour_path']
			faults[f]['requests'][r]['redirect_node'] = requests[r]['faults'][f]['redirect_node']
			faults[f]['requests'][r]['fw_back_path'] = requests[r]['faults'][f]['fw_back_path']
			faults[f]['requests'][r]['detect_node'] = requests[r]['faults'][f]['detect_node']
			
	return requests, faults

def create_ports_dict(G, demands):
	'''
	Creates a dictionary
	ports_dict = {'sx': {'sy': 1, 'sz': 2}, 'sy': {...}, 'hx': {...}, ...}
	'''
	edge_nodes = set([i for i,j in demands]+[j for i,j in demands])

	ports_dict = {}
	for x in G.nodes():
		port_no = 1
		ports_dict['s'+str(x)] = {}
		for y in G.neighbors(x):
			ports_dict['s'+str(x)]['s'+str(y)] = port_no
			port_no += 1
		if x in edge_nodes:
			ports_dict['s'+str(x)]['h'+str(x)] = port_no
			ports_dict['h'+str(x)] = {'s'+str(x) : 0}

	return ports_dict

##########################################################################################
def process_NxN_E2E_PP(N,out_q):
	G, demands = create_square_network(N, link_capacity=N*N*10, demand_volume=1)
	print "\n# Dumb instance "+str(N)+"x"+str(N)+" with end-to-end path protection (bp_node_disj=True...)"
	fc = execute_instance(G, demands, bp_node_disj=True)
	ports_dict = create_ports_dict(G, demands)
	(requests,faults) = create_requests_faults_dict(fc.pps,fc.bps)
	# fictitious filename, just to caching purpose
	filename=str(N)+'X'+str(N)+'E2E.txt'
	(fault_ID, flow_entries_dict, flow_entries_with_timeout_dict, flow_entries_with_burst_dict) = f_t_parser.generate_flow_entries_dict(requests,faults,ports_dict,match_flow=f_t_parser.get_mac_match_mininet,check_cache=False,filename=filename,confirm_cache_loading=False)
	
	flow_stats_dict = f_t_parser.get_flow_stats_dict(flow_entries_dict)
	tot_flows = [flow_stats_dict[node]['tot_flows'] for node in flow_stats_dict.keys() if node!='global']
	'''print 'min',min(tot_flows)
	print 'avg',sum(tot_flows)/float(len((tot_flows)))
	print 'max',max(tot_flows)'''
	stats = [str(N)+"x"+str(N)+" E2E PP",{'min' : min(tot_flows) ,'avg' : sum(tot_flows)/float(len((tot_flows))) , 'max' : max(tot_flows)}]
	out_q.put(stats)
	with open("tmp/"+str(N)+"x"+str(N)+" E2E PP.txt", "a+") as out_file:
		out_file.write(str(stats)+"\n")
	return stats

def process_NxN_greedy(N,out_q):
	G, demands = create_square_network(N, link_capacity=N*N*10, demand_volume=1)	
	print "\n# Smart instance "+str(N)+"x"+str(N)+" with link cost function and bp_node_disj=False..."
	fc = execute_instance(G, demands, cost_func=cost_func_inv)
	ports_dict = create_ports_dict(G, demands)
	(requests,faults) = create_requests_faults_dict(fc.pps,fc.bps)
	# fictitious filename, just to caching purpose
	filename=str(N)+'X'+str(N)+'greedy.txt'
	(fault_ID, flow_entries_dict, flow_entries_with_timeout_dict, flow_entries_with_burst_dict) = f_t_parser.generate_flow_entries_dict(requests,faults,ports_dict,match_flow=f_t_parser.get_mac_match_mininet,check_cache=False,filename=filename,confirm_cache_loading=False)

	flow_stats_dict = f_t_parser.get_flow_stats_dict(flow_entries_dict)
	tot_flows = [flow_stats_dict[node]['tot_flows'] for node in flow_stats_dict.keys() if node!='global']
	'''print 'min',min(tot_flows)
	print 'avg',sum(tot_flows)/float(len((tot_flows)))
	print 'max',max(tot_flows)'''
	
	D = len(demands)
	F = len(G.edges())/2 if isinstance(G,nx.DiGraph) else len(G.edges())
	print 'O(D*F) = %d*%d = %d'%(D,F,D*F)
	stats = [str(N)+"x"+str(N)+" greedy",{'min' : min(tot_flows) ,'avg' : sum(tot_flows)/float(len((tot_flows))) , 'max' : max(tot_flows)}]
	out_q.put(stats)
	with open("tmp/"+str(N)+"x"+str(N)+" greedy.txt", "a+") as out_file:
		out_file.write(str(stats)+"\n")
	return stats

##########################################################################################

def process_network_E2E_PP(net_name,out_q):
	filename_res=topology_dir+"/results.txt."+net_name
	filename_net=topology_dir+"/network.xml."+net_name
	(G, pos, hosts, switches, mapping) = f_t_parser.parse_network_xml(filename=filename_net)
	(requests,faults) = f_t_parser.parse_ampl_results(filename=filename_res)
	print len(requests), 'requests loaded'
	print len(faults), 'faults loaded'
	print 'Network has', len(switches), 'switches,', G.number_of_edges()-len(hosts), 'links and', len(hosts), 'hosts'
	mn_topo = f_t_parser.networkx_to_mininet_topo(G, hosts, switches, mapping)
	ports_dict = f_t_parser.adapt_mn_topo_ports_to_old_API(mn_topo.ports)

	print "\n# Dumb instance "+net_name+" with end-to-end path protection (bp_node_disj=True...)"
	# we take requests just for its keys, but primary/backup paths are calculated by execute_instance()
	demands = {dem : 1 for dem in requests.keys() }
	N = G.number_of_edges()-len(hosts)
	G_dir = G.to_directed()
	for e in G_dir.edges():
		G_dir.edge[e[0]][e[1]] = {'capacity': N*N*10}
	fc = execute_instance(G_dir, demands, bp_node_disj=True)
	(requests_E2E,faults_E2E) = create_requests_faults_dict(fc.pps,fc.bps)
	(fault_ID, flow_entries_dict, flow_entries_with_timeout_dict, flow_entries_with_burst_dict) = f_t_parser.generate_flow_entries_dict(requests_E2E,faults_E2E,ports_dict,match_flow=f_t_parser.get_mac_match_mininet,check_cache=False,filename=filename_res+"E2E",confirm_cache_loading=False)

	flow_stats_dict = f_t_parser.get_flow_stats_dict(flow_entries_dict)
	tot_flows = [flow_stats_dict[node]['tot_flows'] for node in flow_stats_dict.keys() if node!='global']
	'''print 'min',min(tot_flows)
	print 'avg',sum(tot_flows)/float(len((tot_flows)))
	print 'max',max(tot_flows)'''
	stats = [net_name+" E2E PP",{'min' : min(tot_flows) ,'avg' : sum(tot_flows)/float(len((tot_flows))) , 'max' : max(tot_flows)}]
	out_q.put(stats)
	with open("tmp/"+str(net_name)+" E2E PP.txt", "a+") as out_file:
		out_file.write(str(stats)+"\n")
	return stats

def process_network_AMPL_model(net_name,out_q):
	filename_res=topology_dir+"/results.txt."+net_name
	filename_net=topology_dir+"/network.xml."+net_name
	(G, pos, hosts, switches, mapping) = f_t_parser.parse_network_xml(filename=filename_net)
	(requests,faults) = f_t_parser.parse_ampl_results(filename=filename_res)
	print len(requests), 'requests loaded'
	print len(faults), 'faults loaded'
	print 'Network has', len(switches), 'switches,', G.number_of_edges()-len(hosts), 'links and', len(hosts), 'hosts'
	mn_topo = f_t_parser.networkx_to_mininet_topo(G, hosts, switches, mapping)
	ports_dict = f_t_parser.adapt_mn_topo_ports_to_old_API(mn_topo.ports)

	print "\n# Smart instance "+net_name+" with results from AMPL model..."
	(fault_ID, flow_entries_dict, flow_entries_with_timeout_dict, flow_entries_with_burst_dict) = f_t_parser.generate_flow_entries_dict(requests,faults,ports_dict,match_flow=f_t_parser.get_mac_match_mininet,check_cache=False,filename=filename_res,confirm_cache_loading=False)
	
	flow_stats_dict = f_t_parser.get_flow_stats_dict(flow_entries_dict)
	tot_flows = [flow_stats_dict[node]['tot_flows'] for node in flow_stats_dict.keys() if node!='global']
	'''print 'min',min(tot_flows)
	print 'avg',sum(tot_flows)/float(len((tot_flows)))
	print 'max',max(tot_flows)'''

	D = len(requests)
	F = len(faults)
	print 'O(D*F) = %d*%d = %d'%(D,F,D*F)
	stats = [net_name+" AMPL model",{'min' : min(tot_flows) ,'avg' : sum(tot_flows)/float(len((tot_flows))) , 'max' : max(tot_flows)}]
	out_q.put(stats)
	with open("tmp/"+str(net_name)+" AMPL model.txt", "a+") as out_file:
		out_file.write(str(stats)+"\n")
	return stats

if __name__ == '__main__':

	MULTIPROCESSING = False
	NXN_range = [5,6,7] # range(5,16) needs a lot of RAM!
	networks_list = [] #['polska','norway','fat_tree']
	out_q = mp.Queue()
	flow_entries_statistics = {}

	if MULTIPROCESSING:
		# Multiprcessing execution
		processes = []
		for N in NXN_range:
			p = mp.Process(target=process_NxN_E2E_PP,args=(N,out_q))
			processes.append(p)
			p.start()
			'''p = mp.Process(target=process_NxN_greedy,args=(N,out_q))
			processes.append(p)
			p.start()'''
		for net_name in networks_list:
			p = mp.Process(target=process_network_E2E_PP,args=(net_name,out_q))
			processes.append(p)
			p.start()
			'''p = mp.Process(target=process_network_AMPL_model,args=(net_name,out_q))
			processes.append(p)
			p.start()'''

		# Wait for all worker processes to finish
		for p in processes:
			p.join()

		# Collect all results into a single result dict. We know how many dicts
		# with results to expect.
		for p in processes:
			stats = out_q.get()
			flow_entries_statistics[stats[0]] = stats[1]
	else:
		# Sequential execution
		for N in NXN_range:
			stats = process_NxN_E2E_PP(N,out_q)
			flow_entries_statistics[stats[0]] = stats[1]
			'''stats = process_NxN_greedy(N,out_q)
			flow_entries_statistics[stats[0]] = stats[1]'''
		for net_name in networks_list:
			stats = process_network_E2E_PP(net_name,out_q)
			flow_entries_statistics[stats[0]] = stats[1]
			'''stats = process_network_AMPL_model(net_name,out_q)
			flow_entries_statistics[stats[0]] = stats[1]'''

	print
	print
	print flow_entries_statistics
	os.system('sudo mn -c 2> /dev/null')