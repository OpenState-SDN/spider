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
import SPIDER_parser
import os

class SPIDER(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto.OFP_VERSION]
    
    def __init__(self, *args, **kwargs):
        super(SPIDER, self).__init__(*args, **kwargs)

        results_hash = SPIDER_parser.md5sum_results()
        if SPIDER_parser.network_has_changed(results_hash):
            SPIDER_parser.erase_figs_folder()

        (self.requests,self.faults) = SPIDER_parser.parse_ampl_results_if_not_cached()

        print len(self.requests), 'requests loaded'
        print len(self.faults), 'faults loaded'

        print "Building network graph from network.xml..."
        # G is a NetworkX Graph object
        (self.G, self.pos, self.hosts, self.switches, self.mapping) = SPIDER_parser.parse_network_xml()
        print 'Network has', len(self.switches), 'switches,', self.G.number_of_edges()-len(self.hosts), 'links and', len(self.hosts), 'hosts'

        print "NetworkX to Mininet topology conversion..."
        # mn_topo is a Mininet Topo object
        self.mn_topo = SPIDER_parser.networkx_to_mininet_topo(self.G, self.hosts, self.switches, self.mapping)
        # mn_net is a Mininet object
        self.mn_net = SPIDER_parser.create_mininet_net(self.mn_topo)

        SPIDER_parser.launch_mininet(self.mn_net)

        self.ports_dict = SPIDER_parser.adapt_mn_topo_ports_to_old_API(self.mn_topo.ports)

        SPIDER_parser.mn_setup_MAC_and_IP(self.mn_net)

        SPIDER_parser.mn_setup_static_ARP_entries(self.mn_net)

        SPIDER_parser.draw_network_topology(self.G,self.pos,self.ports_dict,self.hosts)

        (self.fault_ID, self.flow_entries_dict, self.flow_entries_with_detection_timeouts_dict, self.flow_entries_with_flowlet_timeouts_dict) = SPIDER_parser.generate_flow_entries_dict(self.requests,self.faults,self.ports_dict,match_flow=SPIDER_parser.get_mac_match_mininet,check_cache=True,dpctl_script=True)

        #SPIDER_parser.print_flow_stats(SPIDER_parser.get_flow_stats_dict(self.flow_entries_dict))

        # Associates dp_id to datapath object
        self.dp_dictionary=dict()
        # Associates dp_id to a dict associating port<->MAC address
        self.ports_mac_dict=dict()

        # Needed by SPIDER_ctrl_REST
        self.SPIDER_parser = SPIDER_parser

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath

        self.ports_mac_dict[datapath.id] = dict()
        self.send_features_request(datapath)
        self.send_port_desc_stats_request(datapath)

        self.configure_stateful_stages(datapath)
        self.install_flows(datapath)
        
        self.dp_dictionary[datapath.id] = datapath

    def install_flows(self,datapath):
        print("Configuring flow table for switch %d" % datapath.id)

        if datapath.id in self.flow_entries_dict.keys():
            for table_id in self.flow_entries_dict[datapath.id]:
                for match in self.flow_entries_dict[datapath.id][table_id]:
                    mod = ofparser.OFPFlowMod(
                        datapath=datapath, cookie=0, cookie_mask=0, table_id=table_id,
                        command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
                        priority=self.flow_entries_dict[datapath.id][table_id][match]['priority'], buffer_id=ofproto.OFP_NO_BUFFER,
                        out_port=ofproto.OFPP_ANY,
                        out_group=ofproto.OFPG_ANY,
                        flags=0, match=match, instructions=self.flow_entries_dict[datapath.id][table_id][match]['inst'])
                    datapath.send_msg(mod)

    def send_features_request(self, datapath):
        req = ofparser.OFPFeaturesRequest(datapath)
        datapath.send_msg(req)

    def configure_stateful_stages(self, datapath):
        node_dict = SPIDER_parser.create_node_dict(self.ports_dict,self.requests)

        self.send_table_mod(datapath, table_id=2)
        self.send_key_lookup(datapath, table_id=2, fields=[ofproto.OXM_OF_ETH_SRC,ofproto.OXM_OF_ETH_DST])
        self.send_key_update(datapath, table_id=2, fields=[ofproto.OXM_OF_ETH_SRC,ofproto.OXM_OF_ETH_DST])

        self.send_table_mod(datapath, table_id=3)
        self.send_key_lookup(datapath, table_id=3, fields=[ofproto.OXM_OF_METADATA])
        self.send_key_update(datapath, table_id=3, fields=[ofproto.OXM_OF_METADATA])

    def configure_global_states(self, datapath):
        for port in self.ports_mac_dict[datapath.id]:
            if port!=ofproto.OFPP_LOCAL:
                (global_state, global_state_mask) = osparser.masked_global_state_from_str("1",port-1)
                msg = osparser.OFPExpSetGlobalState(datapath=datapath, global_state=global_state, global_state_mask=global_state_mask)
                datapath.send_msg(msg)

    def send_table_mod(self, datapath, table_id, stateful=1):
        req = osparser.OFPExpMsgConfigureStatefulTable(datapath=datapath, table_id=table_id, stateful=stateful)
        datapath.send_msg(req)

    def send_key_lookup(self, datapath, table_id, fields):
        key_lookup_extractor = osparser.OFPExpMsgKeyExtract(datapath=datapath, command=osproto.OFPSC_EXP_SET_L_EXTRACTOR, fields=fields, table_id=table_id)
        datapath.send_msg(key_lookup_extractor)

    def send_key_update(self, datapath, table_id, fields):
        key_update_extractor = osparser.OFPExpMsgKeyExtract(datapath=datapath, command=osproto.OFPSC_EXP_SET_U_EXTRACTOR, fields=fields, table_id=table_id)
        datapath.send_msg(key_update_extractor)

    def set_link_down(self,node1,node2):
        if(node1 > node2):
            node1,node2 = node2,node1

        os.system('sudo ifconfig s'+str(node1)+'-eth'+str(self.ports_dict['s'+str(node1)]['s'+str(node2)])+' down')
        os.system('sudo ifconfig s'+str(node2)+'-eth'+str(self.ports_dict['s'+str(node2)]['s'+str(node1)])+' down')

    def set_link_up(self,node1,node2):
        if(node1 > node2):
            node1,node2 = node2,node1

        os.system('sudo ifconfig s'+str(node1)+'-eth'+str(self.ports_dict['s'+str(node1)]['s'+str(node2)])+' up')
        os.system('sudo ifconfig s'+str(node2)+'-eth'+str(self.ports_dict['s'+str(node2)]['s'+str(node1)])+' up')

            
    def send_port_desc_stats_request(self, datapath):
        req = ofparser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)


    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        # store the association port<->MAC address
        for p in ev.msg.body:
            self.ports_mac_dict[ev.msg.datapath.id][p.port_no]=p.hw_addr

        self.configure_global_states(ev.msg.datapath)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath

        pkt = packet.Packet(msg.data)
        header_list = dict((p.protocol_name, p) for p in pkt.protocols if type(p) != str)
        
        #discard IPv6 multicast packets
        if not header_list['ethernet'].dst.startswith('33:33:'):
            print("\nSecond fault detected: packet received by the CTRL")
            print(pkt)

    @set_ev_cls(ofp_event.EventOFPExperimenterStatsReply, MAIN_DISPATCHER)
    def state_stats_reply_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath

        if ev.msg.body.exp_type==0:
            # EXP_STATE_STATS
            stats = osparser.OFPStateStats.parser(ev.msg.body.data, offset=0)
            for stat in stats:
                if stat.entry.key != []:
                    msg = osparser.OFPExpMsgSetFlowState(
                        datapath=dp, state=0, keys=stat.entry.key, table_id=stat.table_id)
                    dp.send_msg(msg)
        elif ev.msg.body.exp_type==1:
            stat = osparser.OFPGlobalStateStats.parser(ev.msg.body.data, offset=0)
            msg = osparser.OFPExpResetGlobalState(datapath=dp)
            dp.send_msg(msg)
            self.configure_global_states(dp)


    def timeout_probe(self,timeout):
        SPIDER_parser.selected_detection_timeouts = timeout

        for datapath_id in self.flow_entries_with_detection_timeouts_dict[timeout]:
            for table_id in self.flow_entries_with_detection_timeouts_dict[timeout][datapath_id]:
                for match in self.flow_entries_with_detection_timeouts_dict[timeout][datapath_id][table_id]:
                    mod = ofparser.OFPFlowMod(
                        datapath=self.dp_dictionary[datapath_id], cookie=0, cookie_mask=0, table_id=table_id,
                        command=ofproto.OFPFC_MODIFY, idle_timeout=0, hard_timeout=0,
                        priority=self.flow_entries_with_detection_timeouts_dict[timeout][datapath_id][table_id][match]['priority'], buffer_id=ofproto.OFP_NO_BUFFER,
                        out_port=ofproto.OFPP_ANY,
                        out_group=ofproto.OFPG_ANY,
                        flags=0, match=match, instructions=self.flow_entries_with_detection_timeouts_dict[timeout][datapath_id][table_id][match]['inst'])
                    self.dp_dictionary[datapath_id].send_msg(mod)

    def timeout_burst(self,burst):
        SPIDER_parser.selected_flowlet_timeouts = burst

        for datapath_id in self.flow_entries_with_flowlet_timeouts_dict[burst]:
            for table_id in self.flow_entries_with_flowlet_timeouts_dict[burst][datapath_id]:
                for match in self.flow_entries_with_flowlet_timeouts_dict[burst][datapath_id][table_id]:
                    mod = ofparser.OFPFlowMod(
                        datapath=self.dp_dictionary[datapath_id], cookie=0, cookie_mask=0, table_id=table_id,
                        command=ofproto.OFPFC_MODIFY, idle_timeout=0, hard_timeout=0,
                        priority=self.flow_entries_with_flowlet_timeouts_dict[burst][datapath_id][table_id][match]['priority'], buffer_id=ofproto.OFP_NO_BUFFER,
                        out_port=ofproto.OFPP_ANY,
                        out_group=ofproto.OFPG_ANY,
                        flags=0, match=match, instructions=self.flow_entries_with_flowlet_timeouts_dict[burst][datapath_id][table_id][match]['inst'])
                    self.dp_dictionary[datapath_id].send_msg(mod)

    def send_state_stats_request(self):
        for datapath_id in self.dp_dictionary:
            req = osparser.OFPExpStateStatsMultipartRequest(datapath=self.dp_dictionary[datapath_id])
            self.dp_dictionary[datapath_id].send_msg(req)

    def send_global_state_stats_request(self):
        for datapath_id in self.dp_dictionary:
            req = osparser.OFPExpGlobalStateStatsMultipartRequest(datapath=self.dp_dictionary[datapath_id])
            self.dp_dictionary[datapath_id].send_msg(req)