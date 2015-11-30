# Readme

1) Follow the instruction at http://openstate-sdn.org/ to install OpenState on a Mininet 2.2.1 VM
2) Configure your VM Manager to forward VM's TCP port 8080 to localhost's TCP port 8080
3) SSH in your VM with X11 forwarding enabled:

	
    $ ssh -X mininet@VM_IP
    

4) Inside Mininet, clone this GitHub repository

	
    $ git clone http://github.com/OpenState-SDN/spider
    

5) Launch SPIDER:
	
    
  	$ cd ~/spider/src
  	$ sudo ryu-manager SPIDER_ctrl_WEBAPP.py
    
    
6) From a browser in your host machine open the following URL: http://localhost:8080/SPIDER

The default topology is a small example network. Is it possible to select other preconfigured topology instances (polska, fat_tree or norway) by renaming them:


	$ cp results.txt.[topo_name] results.txt
	$ cp network.xml.[topo_name] network.xml
    
    
## Authors

* Luca Pollini (<luca.pollini@mail.polimi.it>)
* Davide Sanvito (<davide2.sanvito@mail.polimi.it>)
* Carmelo Cascone (<carmelo.cascone@polimi.it>)
