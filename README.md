SyncJams is a zero-configuration network-synchronised metronome and state-data dictionary for easy collaboration and jamming with electronic music software.

It aims to be plug & play on LANs and WiFi networks and is embeddable in existing applications and music environments.

	Current protocol version: v2

## Shared Data ###

Two types of data are shared between nodes:

 * Timing data - all nodes are synchronised to the same metronome based on network consensus.
 * State data - button states, fader positions, drum sequence data, key tonal information - nodes always sync to the same latest state but rapid chages are throttled and intermediate states may be skipped.

## Protocol ##

SyncJams communicates using the OSC protocol on port 23232 over broadcast UDP packets. For more information and protocol details see [protocol.md](doc/protocol.md).

## Implementations and Platforms ##

Implementations currently exist for Pure Data and Python. See the respective folders in this repository.

## Terminology ##

 * Node - a single instance of software or hardware running the protocol.
 * Address - an OSC style logical address ("key") where a piece of state/data may be shared and is synced.

The protocol is promiscuous - all nodes receive all messages/states but applications only need to listen for the addresses they care about.

## API ##

Methods you can run on the SyncJams object:

	set_state *address* *state-values...* - tell all nodes to set the value at a particular address.
	
	get_state *address* - returns the current values stored at a particular state address.
	
	get_state_keys - returns a list of state key/addresses.
	
	get_node_id - returns the current node id of this node.
	
	get_node_list - returns a list of node_ids of known connected nodes.
	
	send *address* *values...* - send ephemeral values to a particular address at all nodes.

Callbacks/events from the Syncjams object:

	tick *tick-number* *logical-time* - called when a metronome tick happens - logical time is only valid for this node.
	
	state *node-id* *address* *arguments...* - called when node-id has set the state to the value in "arguments" at the address.
	
	node_joined *node-id* - called when node-id joins the network.
	
	node_left *node-id* - called when node-id leaves the network.
	
	message *node-id* *address* *arguments...* - called when an ephemeral message comes in from the network to the address from node-id.
	
	state_keys - returns a list of all addresses currently holding states.
	
	init_event - called once the syncjams library has a uid and is connected to the network ready to send

## Best Practices ##

The only state address/key hardcoded into the protocol and used at the low level is the special "/BPM" state, which sets the number of beats per minute that the network consensus metronome should tick at. This defaults to 180 BPM. The SyncJams implementation listens out for changes to this state to change its own metronome.

In general the state storage system is intended as a minimal way to achieve synchronisation between different electronic music performers. Having too much information (1000s of addresses with lots of data) in the state store will probably degrade performance as new nodes will need to be updated with the entire state dictionary when they join, resulting in a lot of traffic.

Musical information such as tonality of the piece can be stored as a chordname / rootnote pair like this:

 * /key "chord" "CHORDNAME" 60

Or as midi note sets like this (in this case CHORDNAME is purely informational, e.g. for UIs):

 * /key "midichord" "CHORDNAME" 60 65 67 71

Or simply as frequency sets like this (again, CHORDNAME is only informational here):

 * /key "frequencies" "CHORDNAME" 440 660 880

In general clients should try to consume all of these styles of key specification but can send one or more styles of key specification.

You can store several different chord/key entries at different indexes, for example:

 * /key/0 "chord" "maj7" 61
 * /key/1 "frequencies" "gamelan-slendro-1" 262 299 344 398 458 524

See the file [chords.md](doc/chords.md) for a list of western music chord names and their corresponding notes to use (Taken from Benjamin K. Shisler's "Dictionary of Intervals and Chords").

An algorithm for converting midi notes to frequencies ("mtof") taken from Pure Data is here:

	if (m <= -1500) return(0);
	else if (m > 1499) return(mtof(1499));
	else return (8.17579891564 * exp(.0577622650 * m));

Back again ("ftom"):

	return (f > 0 ? 17.3123405046 * log(.12231220585 * f) : -1500)

### More Complex Musical Structures ###

You could store your jam group's suggested chord/key pattern sequence as pairs of (tick-number, key-number), like this:

 * /key/pattern/length 16
 * /key/pattern 0 0 4 1 13 2

If a node wants to store specific information about their own settings they can store them at e.g. /node/NODE-ID/STATENAME. Examples:

 * /node/12345/platform "supercollider" "osx"
 * /node/12345/audio-latency "125ms"
 * /node/12345/loop-legth 16
 * /node/12345/patch-download-url "http://mysite.com/hello.sc"
 * /node/12345/application-url "http://supercollider.github.io/"

By convention, nodes should not overwrite the information stored at another node's private state endpoints.

## Security Model ##

The target application for SyncJams is in music, media, and other recreational/artistic endeavours.

The protocol makes no attempt at security and assumes that everybody on the local network is a trusted participant.

The protocol solves the technical issue of how to share state and timing between collaborating nodes, but not social issues such as who should lead the band or set the BPM. It's assumed that collaborating/jamming humans will work out those things.

Every node has write access to the entire state dictionary, and last-write always takes precedence.

Usually, packets that don't adhere to the protocol correctly are dropped silently, but a wilfully misbehaving node could easily cause disruption and corruption of data, or trivially launch a denial-of-service attack on other nodes.

So don't ask jerks to your jams.

Don't use the SyncJams protocol to store important or valuable information that you don't want other people to be able to see and modify arbitrarily.

## License ##

The SyncJams implementations in this repository are licensed under the terms of the LGPLv3.

Basically this means you can use these implementations in your own code (proprietary or otherwise) but if you modify and distribute the core library code in this repository you must share the changes.

Copyright Chris McCormick, 2014-2015. With huge thanks to Matt Black from Ninjatune for support, ideas, motivational pep-talks.
