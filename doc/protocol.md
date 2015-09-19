SyncJams communicates via the OSC protocol on port 23232 over broadcast UDP sockets.

### Example OSC packets ###

Tick:
	
	/syncjams/tick protocol-version node-id tick-number state-node-id-checksum state-msg-id-checksum state-tick-checksum
	
	/syncjams/tick v2 1234567 23 13 13 13
	
State hash:
	
	/syncjams/state-ids protocol-version node-id state-node-id-1 state-msg-id-1 state-node-id-2 state-msg-id-2...
	
	/syncjams/state-ids v2 1005122 1005122 1
	
State:
	
	/syncjams/state/KEY protocol-version node-id message-id tick-number tick-offset-ms values...
	
	/syncjams/state/BPM v2 7008149 1.0 0.0 0.0 180.0

Message:

	/syncjams/KEY protocol-version node-id message-id values...
	
	/syncjams/hello v2 3034669 2 'What is the quetion?' 42

Leave:

	/syncjams/leave protocol-version node-id msg-id
	
	/syncjams/leave v2 123224 5

### Core ###

SyncJams messages are sent to a set of OSC addresses under the address prefix default of `/syncjams/*`.

Messages are broadcast on the local network using IP addresses 255.255.255.255 and 192.168.43.255 (the latter providing Android tethering network coverage) so that all nodes on a properly configured LAN will receive all packets from eachother.

Each individual SyncJams node (application) must choose a node ID - a randomly selected number between 0 and pow(2, 23) which is the largest accurate integer number that can be represented on platforms which only use a 32 bit float. Seed for randomness using e.g. clock time, node IP address, DAC sample, etc. to try to ensure uniqueness. Probability of node ID collisions is about one in eight million.

There are three major types of SyncJams message: tick, state, and regular message. Two other types of message; leave and state-hash maintain the protocol.

### Tick Message ###

This is the core message type employed by the Syncjams protocol and the method nodes use to keep in time with eachother. Each node keeps its own internal clock running at the BPM found in the state address "/BPM" and consensus is reached because any node that receives a higher tick than expected, earlier than expected, will immediately force its clock to that tick. This means that the fastest packet to be broadcast between nodes is the one that will bring them closer to the same time. Slower packets carrying tick time will be discarded as the node will have already reached the desired tick before the packet arrives.

Tick messages also convey the state-checksums which allow nodes to determine whether they agree on the current values in the state-table. If a node's checksums differ from another node it broadcasts the state-hash message which is a list of unique state keys in the form of (node-id, msg-id) corresponding to the node that set the last state for a key at a particular message number. If another node is missing a state-id that the current node has then it will re-broadcast the full state message. Because states are only ever updated to the latest tick time for a particular state, this ensures state integrity across all nodes - all nodes will always switch to the latest state seen.
