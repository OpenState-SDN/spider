import networkx as nx
from xml.dom import minidom
import time
import fc_lib
import sys
import os.path
from numpy import mean, std

def get_parsed_vals(vals):
	return min(vals), max(vals), mean(vals), std(vals)

def print_statistic(G, fc, demands, allocated_demands, link_util_cap=1):
	#evaluation number of request not allocated
	percentage_dem = float(len(fc.pps))/len(demands) 

	if len(allocated_demands) == 0:
		return

	#evaluation backup path length
	ratios = list()
	total_bp = 0.0
	for (s,t) in fc.pps:
		b = len(fc.pps[s,t]) - 1.0
		if (s,t) in fc.bps: 
			for (n,m) in fc.bps[s,t]:
				ratios.append(((len(fc.bps[s,t][n,m]) - 1.0)/b) - 1)
		total_bp += len(fc.pps[s,t])-1

	print("{:<23} {:.0f}/{:.0f} ({:.0%})".format("PPs allocated:", len(allocated_demands), len(demands), percentage_dem))
	print("{:<23} {:.0f}/{:.0f} ({:.0%})".format("BPs allocated:", len(ratios), total_bp, len(ratios)/total_bp))

	# primary path length evaluation
	pp_lenghts = list()
	for p in fc.pps.values():
		pp_lenghts.append(len(p)-1)

	bp_lenghts = list()
	for (s,t) in fc.bps:
		for (n,m) in fc.bps[s,t]:
			bp_lenghts.append(len(fc.bps[s,t][n,m])-1)

	print "{:<23} min {:5.1f} | max {:5.1f} | avg {:5.1f} (std {:5.1f})".format("PP length:", *get_parsed_vals(pp_lenghts))
	print "{:<23} min {:5.1f} | max {:5.1f} | avg {:5.1f} (std {:5.1f})".format("BP length:", *get_parsed_vals(bp_lenghts))
	print "{:<23} min {:5.0%} | max {:5.0%} | avg {:5.0%} (std {:5.0%})".format("PP/BP length ratio:", *get_parsed_vals(ratios))

	#evaluation link congestion 
	link_usages = list()
	for (i,j) in G.edges():
		b = min([fc.pp_res_caps[i,j]] + fc.lf_res_caps[i,j].values() + fc.nf_res_caps[i,j].values())
		link_usages.append(link_util_cap - (b / float(G.edge[i][j]['capacity'])))
	print "{:<23} min {:5.0%} | max {:5.0%} | avg {:5.0%} (std {:5.0%})".format("Link utilization:", *get_parsed_vals(link_usages))

	#evaluation reverse path length
	reverse_paths = list()
	for (s,t) in fc.pps:
		if (s,t) in fc.bps:
			for (n,m) in fc.bps[s,t]:
				assert fc.bps[s,t][n,m][0] == fc.pps[s,t][0]
				assert fc.bps[s,t][n,m][-1] == fc.pps[s,t][-1]

				#print "Demand {}->{} {}x{}".format(s,t,n,m)
				if n != s:
					d_pos = fc.pps[s,t].index(n)
					for i in range(max(len(fc.bps[s,t][n,m]), len(fc.pps[s,t]))):
						if(fc.bps[s,t][n,m][i] == fc.pps[s,t][i]):
							r_pos = i
						else:
							break;
					#print "PP", fc.pps[s,t]
					#print "BP", fc.bps[s,t][n,m]
					#print "d_pos={}, r_pos={}".format(d_pos, r_pos)
					reverse_paths.append(float(d_pos-r_pos)/d_pos)

					#print r_pos,d_pos,reverse_paths[-1]
	print "{:<23} min {:5.0%} | max {:5.0%} | avg {:5.0%} (std {:5.0%})".format("Reverse path length:", *get_parsed_vals(reverse_paths))

def execute_instance(G, demands, link_util_cap=1, cost_func=None, given_pps=[], bp_node_disj=False):

	fc = fc_lib.Crankbacker(G, link_util_cap)
	t0 = time.clock()
	allocated_demands = fc.allocate_demands(demands, cost_func, given_pps, bp_node_disj)
	t1 = time.clock()

	print "{:<23} {} nodes, {} links, {} demands".format("Network", G.number_of_nodes(), G.number_of_edges(), len(demands))
	print "{:<23} {:.1f}ms, ~{:.2f}ms per demand".format("Execution time:", (t1-t0)*1000, (float(t1-t0)/len(demands))*1000)
	
	print_statistic(G, fc, demands, allocated_demands)

	return fc