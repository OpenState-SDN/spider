from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, HANDSHAKE_DISPATCHER
from ryu.controller.handler import set_ev_cls
import ryu.ofproto.ofproto_v1_3 as ofproto
import ryu.ofproto.ofproto_v1_3_parser as ofparser
import ryu.ofproto.openstate_v1_0 as osproto
import ryu.ofproto.openstate_v1_0_parser as osparser
from ryu.lib.packet import packet
from ryu.topology import event
import logging
from sets import Set
import time
import sys,os
import f_t_parser_ctrl_drop as f_t_parser
from ryu.lib import hub
from datetime import datetime
from time import sleep
import random

class OpenStateFaultTolerance(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto.OFP_VERSION]
    
    def __init__(self, *args, **kwargs):
        super(OpenStateFaultTolerance, self).__init__(*args, **kwargs)
        f_t_parser.generate_flow_entries_dict(GUI=True)

        self.REALIZATIONS_NUM = int(os.environ['REALIZATIONS_NUM'])

        # Associates dp_id to datapath object
        self.dp_dictionary=dict()
        self.ports_mac_dict=dict() 

        # Detect nodes need group entries installation
        self.detect_nodes=Set([])
        for request in f_t_parser.requests:
            for y in range(len(f_t_parser.requests[request]['faults'])):
                self.detect_nodes.add(f_t_parser.requests[request]['faults'].items()[y][1]['detect_node'])

        # Primary path nodes match against "state=0" => they need to have a stateful stage 0
        self.stateful_nodes=Set([])
        for request in f_t_parser.requests:
            for y in range(len(f_t_parser.requests[request]['primary_path'])):
                self.stateful_nodes.add(f_t_parser.requests[request]['primary_path'][y])

        # Needed by fault_tolerance_rest
        self.f_t_parser = f_t_parser

        # switch counter
        self.switch_count = 0

    def save_datapath(self,dp_dictionary,dp_id,dp):
        dp_dictionary = dict(dp_dictionary.items() + [(dp_id, dp)])
        return dp_dictionary

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        pkt = packet.Packet(msg.data)
           
    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status_handler(self, ev):
        msg = ev.msg
        name = msg.desc.name.rsplit('-')[0]
        port_no = msg.desc.port_no

        other = f_t_parser.mn_topo_ports[name] 
        for key in other:
            if other[key]==port_no:
                fault = (int(key[1:]),int(name[1:]))
                if(fault[0] > fault[1]):
                    fault=(fault[1],fault[0])

        if msg.desc.config == 1:
            for request in f_t_parser.faults[fault]['requests']:
                redirect = f_t_parser.requests[request]['faults'][fault]['redirect_node']
                detect = f_t_parser.requests[request]['faults'][fault]['detect_node']
                if redirect!=detect:
                    print("Installing redirect rules in node %d for request %s with fault %s" %(redirect,str(request),str(fault)))
                    for flow_entry in f_t_parser.redirect_detour_dict[(redirect,request,fault)]:
                        mod = ofparser.OFPFlowMod(
                            datapath=self.dp_dictionary[redirect], cookie=0, cookie_mask=0, table_id=flow_entry['table_id'],
                            command=ofproto.OFPFC_MODIFY, idle_timeout=0, hard_timeout=0,
                            priority=32768, buffer_id=ofproto.OFP_NO_BUFFER,
                            out_port=ofproto.OFPP_ANY,
                            out_group=ofproto.OFPG_ANY,
                            flags=0, match=flow_entry['match'], instructions=flow_entry['inst'])
                        self.dp_dictionary[redirect].send_msg(mod)   

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath

        self.ports_mac_dict[datapath.id]={}
        self.send_features_request(datapath)
        self.send_port_desc_stats_request(datapath)
        self.install_flows(datapath,datapath.id in self.detect_nodes,datapath.id in self.stateful_nodes)

        self.dp_dictionary = self.save_datapath(self.dp_dictionary,datapath.id,datapath)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        for p in ev.msg.body:
            self.ports_mac_dict[ev.msg.datapath.id][p.port_no]=p.hw_addr

    def install_flows(self,datapath,has_group,stateful):
        print("Configuring flow table for switch %d" % datapath.id)
        if stateful:
            self.send_table_mod(datapath)
            self.send_key_lookup(datapath)
            self.send_key_update(datapath)

        # group entries installation
        if has_group:
            self.install_group_entries(datapath)

        # flow entries installation
        if datapath.id in f_t_parser.flow_entries_dict.keys():
            for flow_entry in f_t_parser.flow_entries_dict[datapath.id]:
                mod = ofparser.OFPFlowMod(
                    datapath=datapath, cookie=0, cookie_mask=0, table_id=flow_entry['table_id'],
                    command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
                    priority=32768, buffer_id=ofproto.OFP_NO_BUFFER,
                    out_port=ofproto.OFPP_ANY,
                    out_group=ofproto.OFPG_ANY,
                    flags=0, match=flow_entry['match'], instructions=flow_entry['inst'])
                datapath.send_msg(mod)     

        for primary_entry_key in f_t_parser.redirect_primary_dict.keys():
            if primary_entry_key[0]==datapath.id:
                for flow_entry in f_t_parser.redirect_primary_dict[primary_entry_key]:
                    mod = ofparser.OFPFlowMod(
                        datapath=datapath, cookie=0, cookie_mask=0, table_id=flow_entry['table_id'],
                        command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
                        priority=32768, buffer_id=ofproto.OFP_NO_BUFFER,
                        out_port=ofproto.OFPP_ANY,
                        out_group=ofproto.OFPG_ANY,
                        flags=0, match=flow_entry['match'], instructions=flow_entry['inst'])
                    datapath.send_msg(mod)  

        self.switch_count += 1
        if self.switch_count == f_t_parser.G.number_of_nodes():
            self.monitor_thread = hub.spawn(self._monitor,datapath) 

    def send_table_mod(self, datapath):
        req = osparser.OFPExpMsgConfigureStatefulTable(datapath=datapath, table_id=0, stateful=1)
        datapath.send_msg(req)

    def send_features_request(self, datapath):
        req = ofparser.OFPFeaturesRequest(datapath)
        datapath.send_msg(req)

    def send_key_lookup(self, datapath):
        key_lookup_extractor = osparser.OFPExpMsgKeyExtract(datapath, osproto.OFPSC_EXP_SET_L_EXTRACTOR, [ofproto.OXM_OF_ETH_SRC,ofproto.OXM_OF_ETH_DST], table_id=0)
        datapath.send_msg(key_lookup_extractor)

    def send_key_update(self, datapath):
        key_update_extractor = osparser.OFPExpMsgKeyExtract(datapath, osproto.OFPSC_EXP_SET_U_EXTRACTOR, [ofproto.OXM_OF_ETH_SRC,ofproto.OXM_OF_ETH_DST], table_id=0)
        datapath.send_msg(key_update_extractor)

    def set_link_down(self,node1,node2):
        if(node1 > node2):
            node1,node2 = node2,node1

        hw_addr1 = self.ports_mac_dict[self.dp_dictionary[node1].id][f_t_parser.mn_topo_ports['s'+str(node1)]['s'+str(node2)]]
        hw_addr2 = self.ports_mac_dict[self.dp_dictionary[node2].id][f_t_parser.mn_topo_ports['s'+str(node2)]['s'+str(node1)]]
        config = 1
        mask = (ofproto.OFPPC_PORT_DOWN)
        advertise = (ofproto.OFPPF_10MB_HD | ofproto.OFPPF_100MB_FD | ofproto.OFPPF_1GB_FD | ofproto.OFPPF_COPPER |
                     ofproto.OFPPF_AUTONEG | ofproto.OFPPF_PAUSE | ofproto.OFPPF_PAUSE_ASYM)
        req1 = ofparser.OFPPortMod(self.dp_dictionary[node1], f_t_parser.mn_topo_ports['s'+str(node1)]['s'+str(node2)], hw_addr1, config, mask, advertise)
        self.dp_dictionary[node1].send_msg(req1)
        req2 = ofparser.OFPPortMod(self.dp_dictionary[node2], f_t_parser.mn_topo_ports['s'+str(node2)]['s'+str(node1)], hw_addr2, config, mask, advertise)
        self.dp_dictionary[node2].send_msg(req2)

    def set_link_up(self,node1,node2):
        if(node1 > node2):
            node1,node2 = node2,node1

        hw_addr1 = self.ports_mac_dict[self.dp_dictionary[node1].id][f_t_parser.mn_topo_ports['s'+str(node1)]['s'+str(node2)]]
        hw_addr2 = self.ports_mac_dict[self.dp_dictionary[node2].id][f_t_parser.mn_topo_ports['s'+str(node2)]['s'+str(node1)]]
        config = 0
        mask = (ofproto.OFPPC_PORT_DOWN)
        advertise = (ofproto.OFPPF_10MB_HD | ofproto.OFPPF_100MB_FD | ofproto.OFPPF_1GB_FD | ofproto.OFPPF_COPPER |
                     ofproto.OFPPF_AUTONEG | ofproto.OFPPF_PAUSE | ofproto.OFPPF_PAUSE_ASYM)
        req1 = ofparser.OFPPortMod(self.dp_dictionary[node1], f_t_parser.mn_topo_ports['s'+str(node1)]['s'+str(node2)], hw_addr1, config, mask, advertise)
        self.dp_dictionary[node1].send_msg(req1)
        req2 = ofparser.OFPPortMod(self.dp_dictionary[node2], f_t_parser.mn_topo_ports['s'+str(node2)]['s'+str(node1)], hw_addr2, config, mask, advertise)
        self.dp_dictionary[node2].send_msg(req2)

        # "Primary path rules" installation in Redirect only nodes of all the requests involved in fault
        fault=(node1,node2)
        for request in f_t_parser.faults[(fault)]['requests']:
                redirect = f_t_parser.requests[request]['faults'][fault]['redirect_node']
                #print("Installing primary rules in node %d for request %s with fault %s" %(redirect,str(request),str(fault)))
                for flow_entry in f_t_parser.redirect_primary_dict[(redirect,request)]:
                    mod = ofparser.OFPFlowMod(
                        datapath=self.dp_dictionary[redirect], cookie=0, cookie_mask=0, table_id=flow_entry['table_id'],
                        command=ofproto.OFPFC_MODIFY, idle_timeout=0, hard_timeout=0,
                        priority=32768, buffer_id=ofproto.OFP_NO_BUFFER,
                        out_port=ofproto.OFPP_ANY,
                        out_group=ofproto.OFPG_ANY,
                        flags=0, match=flow_entry['match'], instructions=flow_entry['inst'])
                    self.dp_dictionary[redirect].send_msg(mod)

    def install_group_entries(self,datapath):
        for group_entry in f_t_parser.group_entries_dict[datapath.id]:
            buckets = f_t_parser.group_entries_dict[datapath.id][group_entry]
            req = ofparser.OFPGroupMod(datapath, ofproto.OFPGC_ADD,ofproto.OFPGT_FF, group_entry, buckets)
            datapath.send_msg(req)
            
    def send_port_desc_stats_request(self, datapath):
        req = ofparser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    def _monitor(self,datapath):
        hub.sleep(5)
        print("Network is ready")

        hub.sleep(5)
        req_per_fault = {}
        for f in self.f_t_parser.faults:
            req_per_fault[f]=len(self.f_t_parser.faults[f]['requests'])
        worst_fault=max(req_per_fault.iterkeys(), key=lambda k: req_per_fault[k])
        #worst_fault=(7,8)

        fw_back_path_len_per_req = {}
        for r in self.f_t_parser.faults[worst_fault]['requests']:
            if self.f_t_parser.faults[worst_fault]['requests'][r]['fw_back_path']!=None:
                fw_back_path_len_per_req[r]=len(self.f_t_parser.faults[worst_fault]['requests'][r]['fw_back_path'])
            else:
                fw_back_path_len_per_req[r]=0

        # requests passing from worst_link sorted by fw_back_path_len in fw_back_path_len_per_req order
        sorted_req=sorted(fw_back_path_len_per_req,key=fw_back_path_len_per_req.__getitem__,reverse=True)

        RTT_DELAY_LIST = eval(os.environ['RTT_DELAY_LIST'])
        for delay in RTT_DELAY_LIST:
            print("\n\x1B[32mSetting delay switch-CTRL: "+str(delay)+"ms\x1B[0m")
            os.system('sudo tc qdisc change dev lo root netem delay '+str(delay)+'ms')
            i=0
            for sim_num in range(self.REALIZATIONS_NUM):
                print('\n\x1B[32mSTARTING REALIZATION '+str(i+1)+"/"+str(self.REALIZATIONS_NUM)+'\n\x1B[0m')
                count=0
                for req in sorted_req:
                    count+=1
                    print('h'+str(req[0])+'# ping -i '+str(os.environ['interarrival'])+' '+self.f_t_parser.net['h'+str(req[1])].IP()+'&')
                    self.f_t_parser.net['h'+str(req[0])].cmd('ping -i '+str(os.environ['interarrival'])+' '+self.f_t_parser.net['h'+str(req[1])].IP()+'> ~/ping_OF.'+str(req[0])+'.'+str(req[1])+'.'+str(delay)+'rtt.sim'+str(i)+'.txt &')
                    if count==int(os.environ['N']):
                        break

                if os.environ['ENABLE_FAULT']=='yes':
                        hub.sleep(int(os.environ['LINK_DOWN']))      
                        print("LINK DOWN "+str(worst_fault))
                        self.set_link_down(worst_fault[0],worst_fault[1])
                        hub.sleep(int(os.environ['LINK_UP']))
                        print("LINK UP "+str(worst_fault))
                        self.set_link_up(worst_fault[0],worst_fault[1])
                        os.system("sudo kill -SIGINT `pidof ping`")
                        # wait for primary rules
                        hub.sleep(int(os.environ['LINK_UP']))
                i+=1

        os.system("chown mininet:mininet ~/ping_OF*")
        os.system("kill -9 $(pidof -x ryu-manager) 2> /dev/null")
