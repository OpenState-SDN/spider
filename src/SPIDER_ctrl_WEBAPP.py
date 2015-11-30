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

from webob import Response
from ryu.app import wsgi as app_wsgi
from ryu.app.wsgi import ControllerBase, WSGIApplication
from ryu.base import app_manager
import ryu.ofproto.ofproto_v1_3 as ofproto
import ryu.ofproto.ofproto_v1_3_parser as ofparser
import ryu.ofproto.openstate_v1_0 as osproto
import ryu.ofproto.openstate_v1_0_parser as osparser
import SPIDER_ctrl
import os

class NetworkController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(NetworkController, self).__init__(req, link, data, **config)
        self.SPIDER_ctrl = data['SPIDER_ctrl']
        self.SPIDER_parser = data['SPIDER_parser']

    def body_top(self):
        body='<html><head><title>SPIDER</title>'
        body+="""
<style type="text/css">
body {
  color: #666;
  font: 14px/24px "Open Sans", "HelveticaNeue-Light", "Helvetica Neue Light", "Helvetica Neue", Helvetica, Arial, "Lucida Grande", Sans-Serif;
}
.table_buttons table {
  border-collapse: separate;
  border-spacing: 0;
}
.table_buttons th,
td {
  padding: 6px 15px;
}
.table_buttons th {
  background: #42444e;
  color: #fff;
  text-align: center;
  vertical-align: middle;
}
.table_buttons tr:first-child th:first-child {
  border-top-left-radius: 6px;
}
.table_buttons tr:first-child th:last-child {
  border-top-right-radius: 6px;
}
.table_buttons td {
  border-right: 1px solid #c6c9cc;
  border-bottom: 1px solid #c6c9cc;
}
.table_buttons td:first-child {
  border-left: 1px solid #c6c9cc;
}
.table_buttons tr:nth-child(even) td {
  background: #eaeaed;
}
.table_buttons tr:last-child td:first-child {
  border-bottom-left-radius: 6px;
}
.table_buttons tr:last-child td:last-child {
  border-bottom-right-radius: 6px;
}
</style>

<link rel="stylesheet" href="//maxcdn.bootstrapcdn.com/font-awesome/4.5.0/css/font-awesome.min.css">
<script src="//code.jquery.com/jquery-1.11.3.min.js"></script>

<script>
$(document).ready(function()
{
    $("#flowlet_TO_btn").click(function()
    {
        $.post("http://localhost:8080/SPIDER/config_flowlet_to/"+$("#flowlet_timeouts_select option:selected").text());
    });
    $("#detection_TO_btn").click(function()
    {
        $.post("http://localhost:8080/SPIDER/config_detection_to/"+$("#detection_timeouts_select option:selected").text());
    });
    $("#openxterm").click(function()
    {
        $.post("http://localhost:8080/SPIDER/maketerm/"+$("#hostname option:selected").text());
    });
    $("#pingall").click(function()
    {
        $.post("http://localhost:8080/SPIDER/pingall");
    });
    $("#killping").click(function()
    {
        $.post("http://localhost:8080/SPIDER/killping");
    });
    $("#reset").click(function()
    {
        $.post("http://localhost:8080/SPIDER/reset"); 
        window.location.href='http://localhost:8080/SPIDER';
    });
});
function OpenXtermPOST(host)
{
    $.post("http://localhost:8080/SPIDER/maketerm/"+host);
};
function ViewStateTablePOST(host)
{
    $.post("http://localhost:8080/SPIDER/viewstatetable/"+host);
};
function OpenTcpdump(req0,req1,fault0,fault1){
    $.post("http://localhost:8080/SPIDER/opentcpdump/"+req0+"_"+req1+"_"+fault0+"_"+fault1);
};
</script>
</head>
<body><body bgcolor="#FFFFFF">
<center>
<select id="detection_timeouts_select" style="cursor:pointer">
"""
        for i in self.SPIDER_ctrl.flow_entries_with_detection_timeouts_dict:
            detection_TO_str = str(i)
            if self.SPIDER_parser.selected_detection_timeouts==i:
                body+='<option value="'+detection_TO_str+'" selected>'+detection_TO_str+'</option>\n'
            else:
                body+='<option value="'+detection_TO_str+'">'+detection_TO_str+'</option>\n'
        body+='</select><button id="detection_TO_btn" style="cursor:pointer">Set detection timeout</button> | \n'
        body+='<select id="flowlet_timeouts_select" style="cursor:pointer">\n'
        for i in self.SPIDER_ctrl.flow_entries_with_flowlet_timeouts_dict:
            flowlet_TO_str = str(i)
            if self.SPIDER_parser.selected_flowlet_timeouts==i:
                body+='<option value="'+flowlet_TO_str+'" selected>'+flowlet_TO_str+'</option>\n'
            else:
                body+='<option value="'+flowlet_TO_str+'">'+flowlet_TO_str+'</option>\n'
        body+='</select>\n<button id="flowlet_TO_btn" style="cursor:pointer">Set flowlet timeout</button> | \n'
        body+='<select id="hostname" style="cursor:pointer">\n'
        for i in range(len(self.SPIDER_ctrl.mn_net.hosts)):
            host_name = str(self.SPIDER_ctrl.mn_net.hosts[i])
            body+='<option value="'+host_name+'">'+host_name+'</option>\n'
        body+='</select>\n<button id="openxterm" style="cursor:pointer">Open xterm</button> | \n<button id="pingall" style="cursor:pointer">Ping All</button><button id="killping" style="cursor:pointer">Kill Ping</button> | \n<button id="reset" style="cursor:pointer; background-color: #FF0000; color: white">Reset</button>\n</center>'
        body+='<hr>\n'
        return body

    def index(self,req,**_kwargs):
        body=self.body_top()
        body+='<center>'
        body+='<table>\n<tr><td><img src="../figs/network.png" alt="network"></td>'
        body+='<td valign="middle"><select style="cursor:pointer" onchange="this.options[this.selectedIndex].value && (window.location = this.options[this.selectedIndex].value);">'
        body+='\n<option value="">Select a Request</option>\n'
        for req in sorted(self.SPIDER_ctrl.requests.keys()):
            body+='<option value="../SPIDER/req/'+str(req[0])+'_'+str(req[1])+'">('+str(req[0])+','+str(req[1])+')</option>\n'
        body+='</select>\n</td></tr>\n</table>\n</center>\n'
        return Response(status=200,content_type='text/html',body=body)

    def image(self,req,img,**_kwargs):
        f = open('figs/'+img,'r')
        body=f.read()
        return Response(status=200,content_type='image/png',body=body)

    def js(self,req,js_file,**_kwargs):
        f = open('js/'+js_file,'r')
        body=f.read()
        return Response(status=200,content_type='application/javascript',body=body)

    def css(self,req,css_file,**_kwargs):
        f = open('css/'+css_file,'r')
        body=f.read()
        return Response(status=200,content_type='text/css',body=body)  

    def maketerm(self,req,hostname,**_kwargs):
        self.SPIDER_parser.openXterm(hostname=hostname,mn_net=self.SPIDER_ctrl.mn_net)

    def openxtermandexeccmd(self,req,hostname,dest,**_kwargs):
        dest_IP=self.SPIDER_parser.int_to_ip_str(int(dest))                # 10.0.x.x   (interface towards standard network)
        cmd='ping '+dest_IP
        self.SPIDER_parser.openXterm(hostname='h'+hostname,cmd=cmd+';echo;echo;echo Last command: \x1B[32m'+cmd+'\x1B[0m; bash',mn_net=self.SPIDER_ctrl.mn_net)

    def viewstatetable(self,req,hostname,**_kwargs):
        node=int(hostname[1:])
        os.system('xterm -T "STATE TABLE - node '+str(node)+'" -e \'~/dpctl-states-with-names.sh '+str(6633+node)+'; /bin/bash -i\'&')

    def opentcpdump(self,req,req0,req1,fault0,fault1,**_kwargs):
        request=(int(req0),int(req1))
        fault=(int(fault0),int(fault1))
        detect_node=self.SPIDER_ctrl.requests[request]['faults'][fault]['detect_node']
        redirect_node=self.SPIDER_ctrl.requests[request]['faults'][fault]['redirect_node']

        if int(fault1)==detect_node:
            port_towards_fault=self.SPIDER_ctrl.ports_dict['s'+str(detect_node)]['s'+str(fault0)]
        else:
            port_towards_fault=self.SPIDER_ctrl.ports_dict['s'+str(detect_node)]['s'+str(fault1)]

        primary_path = self.SPIDER_ctrl.requests[request]['primary_path']
        node_after_me_in_pp = primary_path[ primary_path.index(redirect_node)+1 ]
        port_towards_primary = self.SPIDER_ctrl.ports_dict['s'+str(redirect_node)]['s'+str(node_after_me_in_pp)]

        detour_path = self.SPIDER_ctrl.requests[request]['faults'][fault]['detour_path']
        node_after_me_in_detour = detour_path[ detour_path.index(redirect_node)+1 ]
        port_towards_detour = self.SPIDER_ctrl.ports_dict['s'+str(redirect_node)]['s'+str(node_after_me_in_detour)]

        if detect_node!=redirect_node:
            cmd='tcpdump -i s'+str(detect_node)+'-eth'+str(port_towards_fault)
            os.system('xterm -T "TCPDUMP - port towards failure @detect" -e \''+cmd+'; echo;echo;echo Last command: \x1B[32m'+cmd+'\x1B[0m; /bin/bash -i\'&')

            cmd='tcpdump -i s'+str(redirect_node)+'-eth'+str(port_towards_primary)
            os.system('xterm -T "TCPDUMP - port towards primary path @redirect" -e \''+cmd+'; echo;echo;echo Last command: \x1B[32m'+cmd+'\x1B[0m; /bin/bash -i\'&')

            cmd='tcpdump -i s'+str(redirect_node)+'-eth'+str(port_towards_detour)
            os.system('xterm -T "TCPDUMP - port towards detour path @redirect" -e \''+cmd+'; echo;echo;echo Last command: \x1B[32m'+cmd+'\x1B[0m; /bin/bash -i\'&')

        else:
            cmd='tcpdump -i s'+str(detect_node)+'-eth'+str(port_towards_fault)
            os.system('xterm -T "TCPDUMP - port towards failure @detect&redirect" -e \''+cmd+'; echo;echo;echo Last command: \x1B[32m'+cmd+'\x1B[0m; /bin/bash -i\'&')

            cmd='tcpdump -i s'+str(detect_node)+'-eth'+str(port_towards_detour)
            os.system('xterm -T "TCPDUMP - port towards detour path @detect&redirect" -e \''+cmd+'; echo;echo;echo Last command: \x1B[32m'+cmd+'\x1B[0m; /bin/bash -i\'&')

    def pingall(self,req,**_kwargs):
        self.SPIDER_parser.pingAll(mn_net=self.SPIDER_ctrl.mn_net)

    def killping(self,req,**_kwargs):
        os.system("kill -9 `pidof ping`")

    def configure_detection_to(self,req,timeouts,**_kwargs):
        self.SPIDER_ctrl.timeout_probe(eval(timeouts))

    def configure_flowlet_to(self,req,timeouts,**_kwargs):
        self.SPIDER_ctrl.timeout_burst(eval(timeouts))

    def reset(self,req,**_kwargs):
        for link in self.SPIDER_ctrl.G.edges():
            self.SPIDER_ctrl.set_link_up(link[0],link[1])
        self.SPIDER_ctrl.send_state_stats_request()
        self.SPIDER_ctrl.send_global_state_stats_request()

    def body_req(self, req1, req2):
        faults = self.SPIDER_ctrl.faults
        fault_ID = self.SPIDER_ctrl.fault_ID
        node_dict = self.SPIDER_parser.create_node_dict(self.SPIDER_ctrl.ports_dict,self.SPIDER_ctrl.requests)

        body='<script language="javascript">function OpenXtermAndExecCmd(host,dest){$.post("http://localhost:8080/SPIDER/openxtermandexeccmd/"+host+"_"+dest);}</script>\n'
        
        body+='<div style="text-align:center"><title>SPIDER</title>\n'
        body+='<center>\n<table>\n<tr><td><img name="net_img" src="/figs/r-'+str(req1)+'-'+str(req2)+'.png" alt="network"></td>\n'
        body+='<td align="center"><h1>Request ('+req1+','+req2+')</h1>\n'
        body+='<table cellspacing=5>\n<tr><td align="center"><h5><a style="text-decoration: none;color: black;" href="javascript:OpenXtermPOST(\'h'+str(req1)+'\')">\n<i class="fa fa-terminal"></i><br>Open h'+str(req1)+'<br>xterm</a></h5></td>\n'
        body+='<td></td><td align="center"><h5><a style="text-decoration: none;color: black;" href="javascript:OpenXtermPOST(\'h'+str(req2)+'\')">\n<i class="fa fa-terminal"></i><br>Open h'+str(req2)+'<br>xterm</a></h5></td>\n'
        body+='<td></td><td align="center"><h5><a style="text-decoration: none;color: black;" href="javascript:OpenXtermAndExecCmd(\''+str(req1)+'\',\''+str(req2)+'\')">\n<i class="fa fa-laptop"></i><i class="fa fa-arrow-right"></i><i class="fa fa-laptop"></i><br>Ping<br>h'+str(req1)+'&rarr;h'+str(req2)+'</a></h5></td>\n'
        body+='<td></td><td align="center"><h5><a style="text-decoration: none;color: black;" href="javascript:OpenXtermAndExecCmd(\''+str(req2)+'\',\''+str(req1)+'\')">\n<i class="fa fa-laptop"></i><i class="fa fa-arrow-left"></i><i class="fa fa-laptop"><br>Ping<br>h'+str(req2)+'&rarr;h'+str(req1)+'</a></h5></td></tr>\n</table>\n'
        request=(int(req1),int(req2))
        
        body+='<center>\n<table class="table_buttons"><thead><tr><th valign="bottom"><h4>Set link down</h4></th><th><h4>View state table</h4></th><th><h4>Open Tcpdump</h4></th></tr></thead>\n<tbody>'
        for link_fault in self.SPIDER_ctrl.requests[request]['faults'].keys():
            body+='<tr><td align="center">\n<button style= "width:80%;cursor:pointer" onmouseover="document.net_img.src=\'/figs/r-'+str(req1)+'-'+str(req2)+'-f-'+str(link_fault[0])+'-'+str(link_fault[1])+'.png\'" onmouseout="document.net_img.src=\'/figs/r-'+str(req1)+'-'+str(req2)+'.png\'" onclick="location.href=\'http://localhost:8080/SPIDER/req/'+str(req1)+'_'+str(req2)+'/down/'+str(link_fault[0])+'_'+str(link_fault[1])+'\'" title="Fault tag = '+str(self.SPIDER_parser.fault_tag(faults,link_fault,fault_ID))+' | HB request tag = '+str(self.SPIDER_parser.HB_req_tag(faults))+' | HB reply tag = '+str(self.SPIDER_parser.HB_reply_tag(faults))+' | Probe D->U tag = '+str(self.SPIDER_parser.probe_down_to_up_tag(link_fault,fault_ID))+'">('+str(link_fault[0])+','+str(link_fault[1])+')</button></h3></td>'
            if self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node']!=self.SPIDER_ctrl.requests[request]['faults'][link_fault]['detect_node']:
                body+='<td align="center">\n<button style= "width:80%;cursor:pointer" onclick="javascript:ViewStateTablePOST(\'s'+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'\')" title="Redirect node = '+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'">Redirect</button>'
                body+='\n<button style= "width:80%;cursor:pointer" onclick="javascript:ViewStateTablePOST(\'s'+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['detect_node'])+'\')" title="Detect node = '+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['detect_node'])+'">Detect</button></td>\n'
            else:
                body+='<td align="center">\n<button style= "width:80%;cursor:pointer" onclick="javascript:ViewStateTablePOST(\'s'+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'\')" title="Detect&Redirect node = '+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'">Det&Red</button></td>\n'
            body+='<td align="center"><a href="javascript:OpenTcpdump(\''+str(req1)+'\',\''+str(req2)+'\',\''+str(link_fault[0])+'\',\''+str(link_fault[1])+'\')"><i class="fa fa-search"></i></a></td></tr>\n'
        body+='</tbody>\n</table>\n<br><input type="button" style="width:40%;cursor:pointer" onclick="location.href=\'/SPIDER\';" value="Return to the home page"/></td></tr>\n</table>\n</center>'
        body += '</div>'
        return body

    def request(self, req, req1, req2, **_kwargs):
        body=self.body_top()

        if not (int(req1),int(req2)) in self.SPIDER_ctrl.requests.keys() and not (int(req2),int(req1)) in self.SPIDER_ctrl.requests.keys():
           body+='<div style="text-align:center"><title>SPIDER</title>\n'
           body+='<font color="red"><h1>Request ('+req1+','+req2+') does not exist</h1></font></div>'
           return Response(status=400,content_type='text/html',body=body)

        if not os.path.isfile("figs/r-"+str(req1)+"-"+str(req2)+".png"):
           self.SPIDER_parser.draw_requests(self.SPIDER_ctrl.G,self.SPIDER_ctrl.pos,self.SPIDER_ctrl.ports_dict,self.SPIDER_ctrl.requests,self.SPIDER_ctrl.faults,self.SPIDER_ctrl.fault_ID,(int(req1),int(req2)))

        body+=self.body_req(req1,req2)
        return Response(status=200,content_type='text/html',body=body)

    def setlinkup(self, req, req1, req2, node1, node2, **_kwargs):
        body=self.body_top()

        if not (int(req1),int(req2)) in self.SPIDER_ctrl.requests.keys() and not (int(req2),int(req1)) in self.SPIDER_ctrl.requests.keys():
           body+='<div style="text-align:center"><title>SPIDER</title>\n'
           body+='<font color="red"><h1>Request ('+req1+','+req2+') does not exist</h1></font></div>'
           return Response(status=400,content_type='text/html',body=body)
        
        if not (int(node1),int(node2)) in self.SPIDER_ctrl.G.edges() and not (int(node2),int(node1)) in self.SPIDER_ctrl.G.edges():
           body+='<div style="text-align:center"><title>SPIDER</title>\n'
           body+='<font color="red"><h1>Set Link Up Function - Link ('+node1+','+node2+') does not exist</h1></font></div>'
           return Response(status=400,content_type='text/html',body=body)
        
        self.SPIDER_ctrl.set_link_up(int(node1),int(node2))

        if not os.path.isfile("figs/r-"+str(req1)+"-"+str(req2)+".png"):
           self.SPIDER_parser.draw_requests(self.SPIDER_ctrl.G,self.SPIDER_ctrl.pos,self.SPIDER_ctrl.ports_dict,self.SPIDER_ctrl.requests,self.SPIDER_ctrl.faults,self.SPIDER_ctrl.fault_ID,(int(req1),int(req2)))
           
        body+=self.body_req(req1,req2)
        return Response(status=200,content_type='text/html',body=body)
        
    def setlinkdown(self, req, req1, req2, node1, node2, **_kwargs):
        faults = self.SPIDER_ctrl.faults
        fault_ID = self.SPIDER_ctrl.fault_ID
        node_dict = self.SPIDER_parser.create_node_dict(self.SPIDER_ctrl.ports_dict,self.SPIDER_ctrl.requests)

        body=self.body_top()

        if not (int(req1),int(req2)) in self.SPIDER_ctrl.requests.keys() and not (int(req2),int(req1)) in self.SPIDER_ctrl.requests.keys():
           body+='<div style="text-align:center"><title>SPIDER</title>\n'
           body+='<font color="red"><h1>Request ('+req1+','+req2+') does not exist</h1></font></div>'
           return Response(status=400,content_type='text/html',body=body)
        
        if not (int(node1),int(node2)) in self.SPIDER_ctrl.G.edges() and not (int(node2),int(node1)) in self.SPIDER_ctrl.G.edges():
           body+='<div style="text-align:center"><title>SPIDER</title>\n'
           body+='<font color="red"><h1>Set Link Down Function - Link ('+node1+','+node2+') does not exist</h1></font></div>'
           return Response(status=400,content_type='text/html',body=body)
        
        self.SPIDER_ctrl.set_link_down(int(node1),int(node2))

        if not os.path.isfile("figs/r-"+str(req1)+"-"+str(req2)+".png"):
           self.SPIDER_parser.draw_requests(self.SPIDER_ctrl.G,self.SPIDER_ctrl.pos,self.SPIDER_ctrl.ports_dict, self.SPIDER_ctrl.requests,self.SPIDER_ctrl.faults,self.SPIDER_ctrl.fault_ID,(int(req1),int(req2)))

        body+='<div style="text-align:center"><title>SPIDER</title>\n'
        body+='<center>\n<table>\n'
        body+='<tr><td><img src="/figs/r-'+str(req1)+'-'+str(req2)+'-f-'+str(node1)+'-'+str(node2)+'.png" alt="network"></td>'
        link_fault=(int(node1),int(node2))
        request=(int(req1),int(req2))
        body+='<td align="center"><h1>Request ('+req1+','+req2+')</h1>'
        body+='<h2>link ('+node1+','+node2+') has been set down</h2>'
        body+='<center>\n<table class="table_buttons"><thead><tr><th><h4>Set link up</h4></th><th><h4>View state table</h4></th><th><h4>Open Tcpdump</h4></th></tr></thead>\n<tbody>\n'
        body+='<tr><td align="center">\n<button style= "width:80%;cursor:pointer" onclick="location.href=\'http://localhost:8080/SPIDER/req/'+str(req1)+'_'+str(req2)+'/up/'+str(node1)+'_'+str(node2)+'\'" title="Fault tag = '+str(self.SPIDER_parser.fault_tag(faults,link_fault,fault_ID))+' | Probe U->D tag = '+str(self.SPIDER_parser.HB_req_tag(faults))+' | Probe D->U tag = '+str(self.SPIDER_parser.probe_down_to_up_tag(link_fault,fault_ID))+'">('+str(node1)+','+str(node2)+')</button></td>'
        if self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node']!=self.SPIDER_ctrl.requests[request]['faults'][link_fault]['detect_node']:
            body+='<td align="center">\n<button style= "width:80%;cursor:pointer" onclick="javascript:ViewStateTablePOST(\'s'+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'\')" title="Redirect node = '+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'">Redirect</button>\n'
            body+='\n<button style= "width:80%;cursor:pointer" onclick="javascript:ViewStateTablePOST(\'s'+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['detect_node'])+'\')" title="Detect node = '+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['detect_node'])+'">Detect</button></td>\n'
        else:
            body+='<td align="center">\n<button style= "width:80%;cursor:pointer" onclick="javascript:ViewStateTablePOST(\'s'+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'\')" title="Detect&Redirect node = '+str(self.SPIDER_ctrl.requests[request]['faults'][link_fault]['redirect_node'])+'">Det&Red</button></td>\n'
        body+='<td align="center"><a href="javascript:OpenTcpdump(\''+str(req1)+'\',\''+str(req2)+'\',\''+str(link_fault[0])+'\',\''+str(link_fault[1])+'\')"><i class="fa fa-search"></i></a></td></tr>\n'     
        body+='</table>\n'
        body+='</td></tr></table>\n</div>'
        return Response(status=200,content_type='text/html',body=body)

class SPIDERRestAPI(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto.OFP_VERSION]
    _CONTEXTS = {
        'wsgi': WSGIApplication,
        'SPIDER_ctrl' : SPIDER_ctrl.SPIDER
    }
    
    def __init__(self, *args, **kwargs):
        super(SPIDERRestAPI, self).__init__(*args, **kwargs)
        wsgi = kwargs['wsgi']
        SPIDER_ctrl = kwargs['SPIDER_ctrl']
        mapper = wsgi.mapper
        wsgi.register(NetworkController,{'SPIDER_ctrl' : SPIDER_ctrl, 'SPIDER_parser': SPIDER_ctrl.SPIDER_parser})
        route_name = 'SPIDER'


        uri = '/SPIDER'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='index',
                  conditions=dict(method=['GET']))

        uri = '/SPIDER/maketerm'
        uri+='/{hostname}'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='maketerm',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/viewstatetable'
        uri+='/{hostname}'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='viewstatetable',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/config_detection_to'
        uri+='/{timeouts}'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='configure_detection_to',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/config_flowlet_to'
        uri+='/{timeouts}'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='configure_flowlet_to',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/reset'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='reset',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/openxtermandexeccmd'
        uri += '/{hostname}_{dest}'
        requirements = {'hostname': app_wsgi.DIGIT_PATTERN,
                        'dest': app_wsgi.DIGIT_PATTERN}
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='openxtermandexeccmd',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/opentcpdump'
        uri += '/{req0}_{req1}_{fault0}_{fault1}'
        requirements = {'req0': app_wsgi.DIGIT_PATTERN,
                        'req1': app_wsgi.DIGIT_PATTERN,
                        'fault0': app_wsgi.DIGIT_PATTERN,
                        'fault1': app_wsgi.DIGIT_PATTERN}
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='opentcpdump',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/pingall'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='pingall',
                  conditions=dict(method=['POST']))

        uri = '/SPIDER/killping'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='killping',
                  conditions=dict(method=['POST']))

        uri = '/js'
        uri+='/{js_file}'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='js',
                  conditions=dict(method=['GET']))

        uri = '/css'
        uri+='/{css_file}'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='css',
                  conditions=dict(method=['GET']))

        uri = '/figs'
        uri += '/{img}'
        s = mapper.submapper(controller=NetworkController)
        s.connect(route_name, uri, action='image',
                  conditions=dict(method=['GET']))

        uri = '/SPIDER/req'
        uri += '/{req1}_{req2}'
        requirements = {'req1': app_wsgi.DIGIT_PATTERN,
                        'req2': app_wsgi.DIGIT_PATTERN}
        
        s = mapper.submapper(controller=NetworkController,
                             requirements=requirements)
        s.connect(route_name, uri, action='request',
                  conditions=dict(method=['GET']))

        uri = '/SPIDER/req'
        uri += '/{req1}_{req2}'
        uri += '/up'
        uri += '/{node1}_{node2}'
        requirements = {'req1': app_wsgi.DIGIT_PATTERN,
                        'req2': app_wsgi.DIGIT_PATTERN,
                        'node1': app_wsgi.DIGIT_PATTERN,
                        'node2': app_wsgi.DIGIT_PATTERN}       
        s = mapper.submapper(controller=NetworkController,
                             requirements=requirements)
        s.connect(route_name, uri, action='setlinkup',
                  conditions=dict(method=['GET']))

        uri = '/SPIDER/req'
        uri += '/{req1}_{req2}'
        uri += '/down'
        uri += '/{node1}_{node2}'
        requirements = {'req1': app_wsgi.DIGIT_PATTERN,
                        'req2': app_wsgi.DIGIT_PATTERN,
                        'node1': app_wsgi.DIGIT_PATTERN,
                        'node2': app_wsgi.DIGIT_PATTERN}
        s = mapper.submapper(controller=NetworkController,
                             requirements=requirements)
        s.connect(route_name, uri, action='setlinkdown',
                  conditions=dict(method=['GET']))
