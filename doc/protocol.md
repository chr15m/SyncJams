SyncJams communicates via the OSC protocol on port 23232 over broadcast UDP sockets.

### Example OSC packets ###

	Tick:
	
	/syncjams/tick node-id tick-number state-node-id-checksum state-msg-id-checksum state-tick-checksum node-id-1 msg-id-1 node-id-2 msg-id-2 node-id-3 msg-id-3 ...
	
	/syncjams/tick 1234567 23 13 13 13 1234567 12 
	
	Leave:
	
	State hash:
	
	State:
	
	Message:

### Core ###

SyncJams messages are sent to a set of OSC addresses under the address prefix default of `/syncjams/*`.

Messages are broadcast on the local network using IP addresses 255.255.255.255 and 192.168.43.255 (the latter providing Android tethering network coverage) so that all nodes on a properly configured LAN will receive all packets from eachother.

Each individual SyncJams node (application) must choose a node ID - a randomly selected number between 0 and pow(2, 23) which is the largest number that can be represented on platforms which only use a 32 bit float. Seed for randomness using e.g. clock time, node IP address, DAC sample, etc. to try to ensure uniqueness. Probability of node ID collisions is about one in eight million.

There are three major types of SyncJams message: tick, state, and regular message. Two other types of message; leave and state-hash maintain the protocol.

### Tick Message ###

This is the core message type employed by the Syncjams protocol and the method nodes use to keep in time with eachother. Each node keeps its own internal clock running at the BPM found in the state address "/BPM" and consensus is reached because any node that receives a higher tick than expected, earlier than expected, will immediately force its clock to that moment in time. This means that the fastest packet to be broadcast between nodes is the one that will bring them closer to the same time. Slower packets carrying tick time will be discarded as the node will have already reached the desired tick before the packet arrives.
