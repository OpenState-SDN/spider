import sys
import networkx as nx
import operator

debug = False

def log_debug(msg):
	if debug:
		print("[DEBUG] " + str(msg))

def edgify(nodelist):
	for i in range(len(nodelist) - 1):
		yield (nodelist[i], nodelist[i+1])

def cost_func_ca(link_cap, res_cap, b, coeff=0.75):
	assert b <= res_cap
	assert res_cap <= link_cap

	if (res_cap == b):
		return sys.maxint
	else:
		return coeff*((float(link_cap)/(res_cap-b))-1)

def cost_func_inv(link_cap, res_cap, b, coeff=0.75):
	if res_cap == 0:
		return sys.maxint
	else:
		return 1.0 / res_cap

def get_backup_path(J, pp, n, weight=None):
	bp = []

	# z rappresenta la posizione del nodo n (detection) rispetto al primary path, 0 se si tratta del primo nodo
	z = pp.index(n)
	if z == 0:
		try:
			bp = nx.shortest_path(J, pp[0], pp[-1], weight=weight)
		except nx.NetworkXNoPath:
			raise Crankbacker.NoBackupPathException()
	else:
		min_len = sys.maxint
		for x in range(z+1):
			# Controllo se la porzione di backup path precedente al nodo di redirect si trova nel grafo residuo, cioe ha abbastanza capacita
			if x > 0 and (pp[x-1],pp[x]) not in J.edges():
				break
			try:
				temp_bps = pp[0:x] + nx.shortest_path(J, pp[x], pp[-1])
				temp_len = x + len(temp_bps)
			except nx.NetworkXNoPath:
				# Try with the following node x+1
				continue
			else:
				if temp_len <= min_len:
					min_len = temp_len
					bp = temp_bps

	if len(bp) > 0:
		return bp
	else:
		raise Crankbacker.NoBackupPathException()

class Crankbacker():

	def __init__(self, G, link_util_cap=1, print_alerts=False):
		self.G = G.copy()
		# TODO estrarre link_caps da G
		# contiene la capacita residua dei link 
		self.dems = dict()
		self.pps = dict()
		self.bps = dict()
		self.link_caps = dict()
		self.pp_res_caps = dict()
		self.lf_res_caps = dict()
		self.nf_res_caps = dict()
		for (i,j) in self.G.edges():
			assert 'capacity' in self.G.edge[i][j], "Missing 'capacity' attribute from edge {},{}".format(i,j)
			cap = self.G.edge[i][j]['capacity'] * link_util_cap
			del self.G.edge[i][j]['capacity']
			self.link_caps[i,j] = cap
			self.pp_res_caps[i,j] = cap
			self.lf_res_caps[i,j] = dict()
			self.nf_res_caps[i,j] = dict()
			for (n,m) in self.G.edges():
				self.lf_res_caps[i,j][n,m] = cap
			for m in self.G.nodes():
				self.nf_res_caps[i,j][m] = cap
		self.print_alerts = print_alerts


	class NoBackupPathException(Exception):
		pass


	def debug_caps(self, s, t, n=None, m=None):
		print("PP[{},{}] > {}".format(s,t, self.pps[s,t]))
		caps = [self.pp_res_caps[i,j] for (i,j) in edgify(self.pps[s,t])]
		print("  caps: {}".format(caps))

	def allocate_demands(self, new_dems, cost_func=None, given_pps=[], bp_node_disj=False):
		# Dizionario per le domande da allocare
		dems_to_allocate = dict()

		if cost_func is not None:
			weighted = True
			w_arg = 'w'
		else:
			weighted = False
			w_arg = None

		for (s,t),b in new_dems.items():

			assert b >= 0, "bandwith must be greater or equal to zero for demand {},{}".format(s,t)
			assert s in self.G.nodes(), "s node {} not found in G".format(s)
			assert t in self.G.nodes(), "t node {} not found in G".format(t)

			free_cap = 0 # capacita da deallocare

			# se la domanda non e mai stata allocata prima
			if (s,t) not in self.dems:
				if b > 0:
					# mi ricordo di processare la domanda
					dems_to_allocate[s,t] = b
				else:
					# b = 0, che cazzo ci fai qui?
					continue
			# se la domanda e stata precedentemente allocata, ma la banda richiesta e maggiore di quella gia allocata
			elif b > self.dems[s,t]:
				# dealloco, rimuovo e mi ricordo di ri-calcolare
				free_cap = self.dems[s,t]
				dems_to_allocate[s,t] = b
			# se la domanda e stata precedentemente allocata, ma la banda richiesta e 0, o minore o uguale di quella gia allocata
			else:
				# dealloco 
				free_cap = self.dems[s,t] - b

			# se ho dichiarato capacita da deallocare, allora procedo
			if free_cap > 0:
				# per ogni link / possibile failure sul primary path
				for (n,m) in edgify(self.pps[s,t]):
					self.pp_res_caps[n,m] += free_cap
					# Se esiste backup path per il caso (s,t) con failure i,j
					if (s,t) in self.bps and (n,m) in self.bps[s,t]:
						# dealloco la capacita sottratta a tutti i link del backup path
						for (i,j) in edgify(self.bps[s,t][n,m]):
							self.lf_res_caps[i,j][n,m] += free_cap
							self.lf_res_caps[i,j][m,n] += free_cap
							self.nf_res_caps[i,j][m] += free_cap

				# se ho richiesto di rimuovere, rimuovo
				if free_cap == self.dems[s,t]:
					del self.pps[s,t]
					del self.bps[s,t]
					del self.dems[s,t]
		"""
		Mi ritrovo adesso con dems_to_allocate per cui devo calcolare il prymary parh
		"""

		log_debug("OK, i've got {} dems to allocate".format(len(dems_to_allocate)))

		#############################################################
		#################  PRIMARY EVALUATION #######################
		#############################################################
		allocated_pps = dict()

		# Scorro le domande in ordine decrescente per b
		for ((s,t),b) in sorted(dems_to_allocate.items(), key=operator.itemgetter(1), reverse=True):

			# elimino dalle domande da processare
			assert (s,t) not in self.pps, "a primary path already exists for demand ({},{}) >> {}".format(s,t,self.pps[s,t])
			assert (s,t) not in self.dems, "dems already contains demand ({},{}) >> {}".format(s,t, self.dems[s,t])

			if (s,t) in given_pps:
				# Se il PP mi e dato, evito di calcolarlo...
				pp = given_pps[s,t]
				log_debug("PP for demand ({},{}) already given: {}".format(s,t,pp))

			else:
				log_debug("Processing PP for demand ({},{}): {}".format(s,t,b))

				# create a copy of the network topology to work on
				removed_edges = []

				# elimino dal grafo tutti i link che a priori non possono ospitare la domanda (perche non c'e capacita sufficiente)
				# Calcolo il costo
				for (i,j) in self.G.edges():
					min_res_cap = min([self.pp_res_caps[i,j]]
							+ self.lf_res_caps[i,j].values()
							+ self.nf_res_caps[i,j].values())
					if b > min_res_cap:
						removed_edges.append((i,j))
					elif weighted:
						self.G[i][j][w_arg] = cost_func(self.link_caps[i,j], min_res_cap, b)

				self.G.remove_edges_from(removed_edges)
				log_debug("Removed edges %s"%removed_edges)

				# calcolo lo shortest path
				try:
					pp = nx.shortest_path(self.G, source=s, target=t, weight=w_arg)
				except nx.NetworkXNoPath:
					if self.print_alerts:
						print "PP skipped for d=({},{}) (No shortest path between s and t)".format(s,t)
					continue;
				finally:
					self.G.add_edges_from(removed_edges)
					log_debug("Re-added edges %s"%(removed_edges))

			# print "pps[{},{}] = {}".format(s,t,self.pps[s,t])
			# OK shortest path found
			self.pps[s,t] = pp
			self.dems[s,t] = b
			allocated_pps[s,t] = b

			pp_edges = [e for e in edgify(self.pps[s,t])]
			for (i,j) in pp_edges:
				#update the reamaining capacity of links used by the evaluated primary pat
				self.pp_res_caps[i,j] -= b
				assert self.pp_res_caps[i,j] >= 0, "BUG? pp_res_caps[{},{}] should be greater or equal to 0, instead its {}. Processing pp for demand {},{}".format(i,j,self.pp_res_caps[i,j],s,t)
				for (n,m) in self.lf_res_caps[i,j]:
					if (n,m) not in pp_edges or (m,n) not in pp_edges:
						self.lf_res_caps[i,j][n,m] -= b
						assert self.lf_res_caps[i,j][n,m] >= 0, "BUG? lf_caps[{},{}][{},{}] should be greater or equal to 0, instead its {}. Processing pp for demand {},{}".format(i,j,n,m,self.lf_res_caps[i,j][n,m],s,t)
				for m in self.nf_res_caps[i,j]:
					if m not in self.pps[s,t]:
						self.nf_res_caps[i,j][m] -= b
						assert self.nf_res_caps[i,j][m] >= 0, "BUG? nf_caps[{},{}][{}] should be greater or equal to 0, instead its {}. Processing pp for demand {},{}".format(i,j,m,self.nf_res_caps[i,j][m],s,t)
							
		#############################################################
		#################	BACKUP EVALUATION #######################
		#############################################################

		for ((s,t),b) in sorted(allocated_pps.items(), key=operator.itemgetter(1), reverse=True):

			log_debug("Processing BP for demand ({},{}): {}".format(s,t,b))

			#for each demand and every link in its primary path we ealuate a new path 
			#in case that the link is not anymore available

			assert (s,t) not in self.bps, "backup paths already exist for demand ({},{}) >> {}".format(s,t, self.bps[s,t])

			# per ogni link / possibile guasto, calcolo il detour
			for (n,m) in edgify(self.pps[s,t]):

				if (s,t) in self.bps:
					assert (n,m) not in self.bps[s,t], "backup paths alread exist for demand ({},{}) for failure ({},{}) >> {}".format(s,t,n,m,self.bps[s,t][n,m])

				removed_edges = []
				if len(self.pps[s,t]) == 2:
					removed_edges.extend([(s,t), (t,s)])
				# rimuovo tutti i nodi (link uescenti/entranti) del pp se ho richiesto un bp node disjoint, altrimenti solo m
				if bp_node_disj:
					nodes_to_remove = self.pps[s,t][1:-1]
				else:
					nodes_to_remove = [m]
				for x in nodes_to_remove:
					if (x == t):
						# se x (cioe m) e il nodo terminal, rimuovo solo il link (n,m) e non tutto il nodo
						removed_edges.extend([(n,m), (m,n)])
					else:
						# rimuovo tutto i link uscenti
						removed_edges.extend(self.G.edges(x))
						# e i link entranti ad m (un po tricky)
						for u in self.G.successors(x):
							if self.G.has_edge(u,x):
								removed_edges.append((u,x))

				# rimuovo tutti i link per cui non c'e capacita sufficiente, sia in caso di link failure, che in caso di node failure
				for (i,j) in self.G.edges():
					min_res_cap = min(self.lf_res_caps[i,j][n,m], self.lf_res_caps[i,j][m,n], self.nf_res_caps[i,j][m])
					if b > min_res_cap:
						removed_edges.append((i,j))
					elif weighted:
						self.G[i][j][w_arg] = cost_func(self.link_caps[i,j], min_res_cap, b)

				self.G.remove_edges_from(removed_edges)
				log_debug("Removed edges %s"%removed_edges)

				try:
					bp = get_backup_path(self.G, pp=self.pps[s,t], n=n, weight=w_arg)
				except self.NoBackupPathException:
					if self.print_alerts:
						print "BP skipped for d=({},{}), f=({},{}) (No path between s and t)".format(s,t,n,m)
					# Next failure
					continue;
				else:
					if (s,t) not in self.bps:
						self.bps[s,t] = dict()
					self.bps[s,t][n,m] = bp
					# Update residual capacity
					for (i,j) in edgify(self.bps[s,t][n,m]):
						self.lf_res_caps[i,j][n,m] -= b
						self.lf_res_caps[i,j][m,n] -= b
						self.nf_res_caps[i,j][m] -= b
						assert self.lf_res_caps[i,j][n,m] >= 0, "BUG? lf_caps[{},{}][{},{}] should be greater or equal to 0, instead its {}. Processing bp for demand {},{}".format(i,j,n,m,self.lf_res_caps[i,j][n,m],s,t)
						assert self.lf_res_caps[i,j][m,n] >= 0, "BUG? lf_caps[{},{}][{},{}] should be greater or equal to 0, instead its {}. Processing bp for demand {},{}".format(i,j,m,n,self.lf_res_caps[i,j][m,n],s,t)
						assert self.nf_res_caps[i,j][m] >= 0, "BUG? nf_caps[{},{}][{}] should be greater or equal to 0, instead its {}. Processing bp for demand {},{}".format(i,j,m,self.nf_res_caps[i,j][m],s,t)
				finally:
					self.G.add_edges_from(removed_edges)
					log_debug("Re-added edges %s"%removed_edges)
		
		##############################################
		################# DONE #######################
		##############################################

		return allocated_pps