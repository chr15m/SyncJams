#!/usr/bin/env python

# PEP8 all up in here:
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4 smartindent

import socket
import time
import sys
import logging
from random import randint

import OSC

PORT = 23232

ANY = '0.0.0.0'
ADDRESSES = {
    "broadcast": '<broadcast>',
    "android": '192.168.42.255',
    "localhost": '127.0.0.1'
    # "multicast": '239.255.232.32',
}

# default namespace for syncjams group of nodes
NAMESPACE = "/syncjams"

# number of messages we will keep around for clients that miss some
STORE_MESSAGES = 100
# how many seconds before we decide a node has left
NODE_TIMEOUT = 30
# how long to leave between state updates (throttle fast state changes)
STATE_THROTTLE_TIME = 0.007
# syncjams protocol information
PROTOCOL_VERSION = "v1"

class SyncjamsNode:
    """
        Network synchronised metronome and state for jamming with music applications.
    """
    def __init__(self, initial_state={}, namespace=NAMESPACE, port=None, loglevel=logging.ERROR, logfile=None):
        # set up basic logging
        logging_config = {"level": loglevel}
        if logfile:
            logging_config["filename"] = logfile
        logging.basicConfig(**logging_config)
        # basic configuration to separate this network singleton from another
        self.port = port or PORT
        self.namespace = namespace
        # my randomly chosen NodeID
        # (2^23-1 can be represented completely in 32-bit floating point, which some platforms require)
        # about one in eight million chance of collision
        self.node_id = randint(1, pow(2, 23))
        # increment our message id every time we send
        self.message_id = 0
        # whether or not the server is running
        self.running = False
        # collection of key->(node_id, message_id, tick, time_offset, value) state variables
        self.states = {}
        # collection of last message_ids from other clients nodeID -> message_id
        self.last_messages = {}
        # last time we saw a client nodeID -> our_timestamp
        self.last_seen = {}
        # last tick that happened (number, time)
        self.last_tick = (0, time.time())
        # queue of non-tick messages we have sent
        self.sent_queue = []
        # check sum of state that we send to see if all nodes are in agreement (checksum_name, state:client_id, state:msg_id, state:tick)
        self.state_checksums = [0, 0, 0]
        # queue for outgoing state messages that are being throttled (address -> last_sent_time, message)
        self.state_throttle_queue = {}
        # set up an osc sender to send out broadcast messages
        self.sender = self._make_sender()
        # set up servers to listen on each broadcast address we want to listen on
        # self.listeners = [SyncjamsListener(ADDRESSES["multicast"], self.port, callback=self.osc_message_handler)]
        self.listeners = [SyncjamsListener(ANY, self.port, callback=self._osc_message_handler)]
        # initial BPM state is required
        initial_state["/BPM"] = 180
        # start by establishing my initial state
        for s in initial_state:
            self.set_state(s, initial_state[s])
    
    def set_state(self, address, state=[]):
        """
            Try to set a particular state variable on all nodes.
            Good for persistent information like song key, controller position, etc.
            Nodes will always get most recent state but may not get intermediate states.
            State updates that happen too fast for the network (e.g. fast fader move) will be throttled to 7ms intervals.
        """
        if not address.startswith("/"):
            raise SyncjamsException("State address must start with '/'.")
        if not type(state) in [list, tuple, int, float, str]:
            raise SyncjamsException("State value must be of list, tuple, int, float, or string type.")
        if type(state) in [list, tuple] and len([s for s in state if s is None]):
            raise SyncjamsException("State values must not be None.");
        # get the current time
        now = time.time()
        # put together the message we are going to send
        state_message = [self.last_tick[0], now - self.last_tick[1]] + (type(state) in [list, tuple] and state or [state])
        # check the state throttle queue to make sure we're not sending to one address too fast
        state_queue = self.state_throttle_queue.get(address, [0, None])
        # is the state we are changing on the outgoing queue already?
        if state_queue[0] + STATE_THROTTLE_TIME > now:
            # retain the previous send time
            state_queue[1] = state_message
            # update the state queue entry for this address instead of sending it now
            self.state_throttle_queue[address] = state_queue
        else:
            # set the last sent time in the throttle queue
            self.state_throttle_queue[address] = [now, None]
            # send immediately to the network
            self._send("/state" + address, state_message)
    
    def get_state(self, address):
        state = self.states.get(address, [None, None, None, None, None])[-1]
        return len(state) == 1 and state[0] or state
    
    def get_node_id(self):
        """ Returns this node's unique ID. """
        return self.node_id
    
    def get_node_list(self):
        """ Returns a list of all known nodes currently connected to the group. """
        return self.last_seen.keys()
    
    def send(self, address, value=[]):
        """ Broadcast an arbitrary message to all nodes. Good for ephemeral rhythm/trigger information. Will always be received in order. """
        if not type(value) in [list, tuple, int, float, str]:
            raise SyncjamsException("Message value must be of list, tuple, int, float, or string type.")
        if type(value) in [list, tuple] and len([v for v in value if v is None]):
            raise SyncjamsException("Message value must not contain None.");
        self._send(address, value)
    
    def poll(self):
        """ Run the SyncJams inner loop once, processing network messages etc. Good to call once for every frame of audio data processed. """
        for s in self.listeners:
            s.handle_request()
        self._process_tick()
    
    def serve_forever(self):
        """ Set up a loop running the poll() method until close() is called. Good to call inside a Thread. """
        self.running = True
        while self.running:
            self.poll()
            time.sleep(0.001)
    
    def close(self):
        """ Shut down the server and quit the serve_forever() loop, if running. """
        self._send("/leave")
        self.running = False
        [s.close() for s in self.listeners]
        self.sender.close()
    
    ### Methods to override. ###
    
    def tick(self, tick, time):
        """ A network-consensus metronome tick. """
        pass
    
    def message(self, node_id, address, *args):
        """ A message that has been broadcast by a node. """
        pass
    
    def state(self, node_id, address, *args):
        """ A state variable that has been set by a node. """
        pass
    
    def node_joined(self, node_id):
        """ This node has seen another node for the first time. """
        pass
    
    def node_left(self, node_id):
        """ A node has left the group or timed out. """
        pass
    
    ### Private methods. ###
    
    def _process_tick(self):
        last_tick = self.last_tick[1]
        now = time.time()
        tick_length = self._tick_length()
        # while our metronome is behind, catch it up
        while self.last_tick[1] + tick_length < now:
            # calculate new tick position and time
            self.last_tick = (self.last_tick[0] + 1, self.last_tick[1] + tick_length)
            # register the current new tick so we can run code
            self.tick(*self.last_tick)
        # if the tick changed then broadcast the tick we think we are up to
        if last_tick != self.last_tick[1]:
            self._broadcast_tick()
            # every tick forget about any nodes we haven't seen in a while
            self._forget_old_nodes(now)
        # check for any states that have been throttled to now be sent
        self._send_queued_states(now)
    
    def _forget_old_nodes(self, now, forget=[]):
            # find nodes we have not heard from for more than timeout
            forget = forget + [node_id for node_id in self.last_seen if (self.last_seen[node_id] + NODE_TIMEOUT < now)]
            if forget:
                logging.info("forgetting nodes %s" % forget)
            # remove references to those nodes
            for node_id in forget:
                # actually remove this node from all of our lists
                del self.last_seen[node_id]
                if self.last_messages.has_key(node_id):
                    del self.last_messages[node_id]
                # run the node_left callback method
                self.node_left(node_id)
    
    def _update_state_checksums(self):
            # for the first three elements of each state (node_id, msg_id, tick)
            # generate a checksum based on the sorted list of those values
            state_checksums = []
            for x in range(3):
                sum_source = sorted([self.states[s][x] for s in self.states])
                state_checksums.append(self._array_checksum(sum_source))
            self.state_checksums = state_checksums
            logging.info("Updated state checksums %s" % self.state_checksums)
    
    def _broadcast_tick(self):
        # broadcast what we think the current tick is to the network
        # and checksums for what we think current state is
        # and also our last known message IDs from all peers
        # around 50 peers this will exceed typical 512 byte UDP packet size
        self._send_one_to_all("/tick",
            [self.node_id, self.last_tick[0]] +
            self.state_checksums +
            sum([[m, self.last_messages[m]] for m in self.last_messages], [])
        )
    
    def _broadcast_state_ids(self):
        # broadcast what we think the current state map is - (node_id, msg_id) pairs are unique
        self._send_one_to_all("/state-ids", [self.node_id] + sum([self.states[s][:2] for s in self.states], []))
    
    def _send_queued_states(self, now):
        # make a copy because we might happen in a thread
        throttle_queue = self.state_throttle_queue.copy()
        for s in throttle_queue:
            state_queue = throttle_queue[s][:]
            # is the state we are changing on the outgoing queue already?
            if state_queue[1] and state_queue[0] + STATE_THROTTLE_TIME < now:
                # set the last sent time in the throttle queue
                self.state_throttle_queue[s] = [now, None]
                # send immediately to the network
                self._send("/state" + s, state_queue[1])
    
    def _send(self, address, message=[]):
        if not address.startswith("/"):
            raise SyncjamsException("Address must start with '/'.")
        # message_id increments for every message
        self.message_id += 1
        # set up the outgoing message
        outgoing = []
        # add the default syncjams parameters - node_id and message_id
        outgoing.append(self.node_id)
        outgoing.append(self.message_id)
        # add whatever other data the user wants to send
        if type(message) in [list, tuple]:
            for m in message:
                outgoing.append(m)
        else:
            outgoing.append(message)
        # push the message onto our queue of potential repeats
        self.sent_queue.append((self.message_id, address, outgoing))
        # make sure our queue of sent messages stays an ok size
        self.sent_queue = self.sent_queue[-STORE_MESSAGES:]
        # send the message to all broadcast networks
        self._send_one_to_all(address, outgoing)
    
    # message-handler function that servers will call when a message is received.
    def _osc_message_handler(self, addr, tags, packet, source):
        logging.debug("raw packet %s %s" % (addr, packet))
        
        # bail if incoming packets are not addressed to our top level namespace
        if not addr.startswith(self.namespace):
            self.drop("Bad namespace", addr, tags, packet, source)
            return
        
        # bail if we don't know the version of syncjams
        version = packet.pop(0)
        if version != PROTOCOL_VERSION:
            self._drop("Wrong protocol version", addr, tags, packet, source)
            return
        
        # every message should contain the other client's id
        node_id = self._parse_number_slot(packet)
        # bail if there wasn't a valid client id
        if not node_id:
            self._drop("No node_id", addr, tags, packet, source)
            return
        
        # digestible format for our address routing
        route = addr[len(self.namespace) + 1:].split("/")
        
        # bail if invalid address - no components
        if not len(route):
            self._drop("No valid address", addr, tags, packet, source)
            return
        
        # consensus metronome sync message
        if route[0] == "tick":
            # which tick does the other client think we are up to
            tick = self._parse_number_slot(packet)
            # if the tick is higher than we expect at this point in time
            if tick > self.last_tick[0]:
                # jump to the new tick and reset our tick timer to this moment
                self.last_tick = (tick, time.time())
                # register the current new tick so we can run code
                self.tick(*self.last_tick)
                # send out our new tick anyway so everyone learns our last_message list
                self._broadcast_tick()
            # remainder of the tick message is their state checksums and then last node message ids
            state_checksums = packet[:3]
            message_ids = packet[3:]
            # build a dictionary of their known nodes and latest message ids
            their_latest_messages = dict([(message_ids[x*2], message_ids[x*2+1]) for x in range(len(message_ids) / 2)])
            # if this node does not know us yet and we have messages on our outgoing queue
            if not their_latest_messages.has_key(self.node_id) and self.sent_queue:
                # just send them the last item on our queue
                self._send_one_to_all(self.sent_queue[-1][1], self.sent_queue[-1][2])
            else:
                # otherwise send through all messages from me that they are missing message_id, address, message
                [self._send_one_to_all(m[1], m[2]) for m in self.sent_queue if m[0] > their_latest_messages.get(self.node_id, 0)]
            # compare their state checksums to our own
            if state_checksums != self.state_checksums:
                logging.info("State checksums don't match, broadcasting state hash.");
                # if we disagree about global state, broadcast what we think global state is
                self._broadcast_state_ids()
            # if this is the first time we have seen this node then run the callback method
            if not self.last_seen.has_key(node_id):
                self.node_joined(node_id)
            # update the last seen time
            self.last_seen[node_id] = time.time()
        
        # message that a node has left the network
        elif route[0] == "leave":
            self._forget_old_nodes(time.time(), [node_id])
        
        # packet containing what another client thinks is current state
        elif route[0] == "state-ids":
            # build a list of their state unique id keys (node_id, message_id) 
            their_state_keys = [tuple(packet[x:x+2]) for x in xrange(0, len(packet), 2)]
            # find states they don't have, and which are older than 3 ticks
            for s in self.states:
                if not tuple(self.states[s][:2]) in their_state_keys and self.states[s][2] + 3 < self.last_tick[0]:
                    # rebroadcast the state message
                    self._send_one_to_all("/state" + s, self.states[s])
                    logging.info("Rebroadcasting state: %s = %s" % (s, self.states[s]))
        
        # packet updating client state or message
        else:
            # every message should contain a message id
            message_id = self._parse_number_slot(packet)
            # if we've never seen this node before (or haven't seen them for ages) treat the message as message-counter-reset
            if not self.last_messages.has_key(node_id) or message_id < self.last_messages.get(node_id, sys.maxint) - STORE_MESSAGES:
                self.last_messages[node_id] = message_id
            # otherwise if this is the next in the sequence from this client then increment that counter
            elif message_id == self.last_messages.get(node_id, 0) + 1:
                self.last_messages[node_id] = message_id
                # run the message callback if this isn't a state message
                if route[0] != "state":
                    self.message(node_id, "/" + "/".join(route), *packet)
            # with state messages, we only really care about timestamp - just want the latest
            if route[0] == "state":
                # when was this state change according to consensus clock
                tick = self._parse_number_slot(packet)
                timediff = self._parse_number_slot(packet, convert=float)
                # what key the state change is stored on
                key = "/" + "/".join(route[1:])
                # tick, time_offset, value
                if not self.states.has_key(key) or self.states[key][2] < tick or (self.states[key][2] == tick and self.states[key][3] < timediff):
                    self.states[key] = [node_id, message_id, tick, timediff, packet]
                    # run the state change callback
                    self.state(node_id, key, *packet)
                    # update our state checksums
                    self._update_state_checksums()
    
    def _send_one_to_all(self, address, message):
        # set up the new OSC message to be sent out
        oscmsg = OSC.OSCMessage()
        oscmsg.setAddress(self.namespace + address)
        # add the version number first
        oscmsg.append(PROTOCOL_VERSION)
        # add the message parts to it
        [oscmsg.append(m) for m in message]
        logging.debug("raw sent packet %s" % (oscmsg,))
        # send one message out to all broadcast/multicast networks possible, ignoring errors
        for a in ADDRESSES:
            try:
                return self.sender.sendto(oscmsg, (ADDRESSES[a], self.port))
            except OSC.OSCClientError, e:
                # silently drop socket errors because we'll just keep trying
                # TODO: log
                logging.warning("Dropped message send:")
                logging.warning(oscmsg)
                logging.warning(e)
    
    ### Utility methods. ###
    
    def _array_checksum(self, values):
        # takes a sorted array of numbers and computes a simple checksum
        #
        # hacked version of djb2 hash - well actually not djb2 but:
        # "another version of this algorithm [djb2] (now favored by bernstein)"
        # http://www.cse.yorku.ca/~oz/hash.html
        # 
        # our 32bit clamping hack works for inputs up to pow(2, 23) - good for systems where everything is floating point
        # 
        # Reasons this weak checksum is probably ok to use in this protocol:
        # * Most of the time, states will be changing often (controller data) so the checksums will change often and collisions won't last long.
        # * We are checksumming three different pieces of data so a simultaneous collision on all three is much less likely.
        # * This checksum is very fast, and very simple to implement across varied platforms.
        #
        # test values:
        # s._array_checksum([12, 432, 3, 0, 2343]) == 28632
        # s._array_checksum([0.223, 4234, 0.242435, .76653, 3, 23.35, 656, 43]) == 37187
        # s._array_checksum([122112, 4321, 123, 11, 14, 4, 43, 8388606, 3, 432, 545]) == 36600
        h = 5381
        for v in values:
            h = ((int(int(33 * h) % 65535) ^ int(v % 65535)) % 65535)
        return h
    
    def _tick_length(self):
        try:
            bpm = float(self.states["/BPM"][-1][0])
        except ValueError:
            bpm = 180
        except IndexError:
            bpm = 180
        return 60.0 / bpm
    
    def _parse_number_slot(self, packet, idx=0, convert=int):
        try:
            return convert(packet.pop(idx))
        except ValueError:
            pass
        except IndexError:
            pass
    
    def _drop(self, message, addr, tags, packet, source, route=None):
        logging.debug("DROPPED (%s) from %s" % (message, OSC.getUrlStr(source)))
        logging.debug("\taddr: %s" % addr)
        logging.debug("\ttypetags: %s" % tags)
        logging.debug("\tdata: %s" % packet)
        if route:
            logging.debug("\troute: %s" % route)
    
    def _make_sender(self):
        # OSCClient that sends with broadcast flags on from any assigned port
        sender = OSC.OSCClient()
        sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sender.socket.bind((ANY, 0))
        sender.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        return sender

class SyncjamsException(Exception):
    pass

# class that can listen out on a particular ip - reused to listen on different broadcast subnets
class SyncjamsListener(OSC.OSCServer):
    client = None
    socket_timeout = 0
    def __init__(self, address, port, callback, *args, **kwargs):
        # check whether we have been asked to listen on a multicast address
        self.multicast = address.startswith("239.255") or address.startswith("224.")
        self.address = address
        # set up the OSC server to listen
        OSC.OSCServer.__init__(self, (self.multicast and ANY or address, port), *args, **kwargs)
        # whatever messages come in, run the main callback
        self.addMsgHandler("default", callback)
    
    def server_bind(self):
        # allow multiple receivers on the same IP
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # allow sending to broadcast networks
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # allow port re-use on platforms that require the flag
        if 'SO_REUSEPORT' in vars(socket):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        # ask the OSC library to bind to ports etc
        result = OSC.OSCServer.server_bind(self)
        # finally set the multicast options if this is a multicast socket
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        if self.multicast:
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(self.address) + socket.inet_aton(ANY))
        return result

# Test code for running an interactive version that prints results
if __name__ == "__main__":
    import sys
    from threading import Thread

    # setup handler for receiving message from syncjams network
    class TestSyncjamsNode(SyncjamsNode):
        def tick(self, tick, time):
            if not tick % 16:
                print "Tick %d at %s" % (tick, time)
        
        def state(self, node_id, address, *state):
            print "State update: %s = %s (from node %d)" % (address, str(state), node_id)
        
        def message(self, node_id, address, *message):
            print "Message to %s = %s (from node %d)" % (address, message, node_id)
        
        def node_joined(self, node_id):
            print "Node %d joined." % node_id
        
        def node_left(self, node_id):
            print "node %d left." % node_id
    
    # Start a test syncjams instance
    s = TestSyncjamsNode(loglevel=len(sys.argv) > 1 and getattr(logging, sys.argv[1]) or logging.ERROR)
    print "Starting SyncJams node ID =", s.get_node_id()
    st = Thread( target = s.serve_forever )
    st.start()
    
    banner = """SyncjamsNode is 's'. Examples:
        s.set_state('/fader/volume', 12)
        s.set_state('/key/0', [60, 64, 67])
        s.set_state('/BPM', 145)
        s.send('/endpoint/test', "This is my message.")
    """
    try:
        from IPython.terminal.embed import InteractiveShellEmbed
        InteractiveShellEmbed(banner1=banner)()
    except ImportError:
        import code
        code.InteractiveConsole(locals=globals()).interact(banner)
    
    print "Shutting down SyncJams node."
    s.close()
    print "Waiting for thread to finish."
    st.join()
    print "Done."

