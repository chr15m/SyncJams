SyncJams is a zero-configuration network-syncronising metronome for easy collaboration and jamming in electronic music settings. It aims to be plug'n'play on local area networks and is embeddable in existing applications with C and Python implementations, and algorithmic music making environments like Pure Data and SuperCollider. It also includes a message/state sharing layer allowing nodes to communicate other information over the same channel with no configuration.

## Protocol ##

### Core ###

SyncJams uses the OSC protocol on port 23232 (UDP socket with SO_REUSEADDR flag set).

All SyncJams messages are sent to a set of OSC addresses under the address prefix `/syncjams/*`.

Messages are broadcast on the local network using IP addresses 255.255.255.255 and 192.168.43.255 (Android tethering network coverage) so that all nodes on a properly configured LAN may receive them.

Each individual SyncJamm node (application) must choose a ClientID - a randomly selected 32 bit integer between 0 and pow(2, 32) (Seed for randomness using e.g. clock time, node IP address, DAC sample, etc. to ensure uniqueness).

All SyncJamm messages must include two integer fields as their first OSC elements:

 * ClientID as specified above.
 * MessageID - a value that starts at 0 and increments for each message broadcast.

When a node receives a message with ClientID and MessageID that it has not yet seen, it will re-broadcast them once to increase the robustness of the UDP transport layer.

### Message Types ###

 * `/syncjams/netro/TIMER-NAME ...` - Messages for synchronising metronomes.

 * `/syncjams/netsync/FIELD-NAME ...` - Messages for storing and sharing state.

 * `/syncjames/ADDRESS ...` - Custom user messages sent over the same channel.

