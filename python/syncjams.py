#!/usr/bin/env python

# PEP8 all up in here:
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4 smartindent

import OSC
import socket
import time
from random import randint

PORT = 23232

ANY = '0.0.0.0'
ADDRESSES = {
    "broadcast": '<broadcast>',
    "android": '192.168.42.255',
    # "multicast": '239.255.232.32',
}

# default namespace for syncjams group of nodes
NAMESPACE = "/syncjams"

# number of messages we will keep around for clients that miss some
STORE_MESSAGES = 100
# how many seconds before we decide a node has left
NODE_TIMEOUT = 30

class SyncjamsNode:
    """
        Network synchronised metronome and state for jamming with music applications.
    """
    def __init__(self, latency_ms=0, namespace=NAMESPACE, port=None, debug=False):
        self.debug = debug
        self.port = port or PORT
        self.namespace = namespace
        # set up servers to listen on each broadcast address we want to listen on
        # self.listeners = [SyncjamsListener(ADDRESSES["multicast"], self.port, callback=self.osc_message_handler)]
        self.listeners = [SyncjamsListener(ANY, self.port, callback=self._osc_message_handler)]
        # set up an osc sender to send out broadcast messages
        self.sender = self._make_sender()
        # my randomly chosen NodeID
        self.node_id = randint(0, pow(2, 30))
        # increment a message id every time we send
        self.message_id = 0
        # whether or not the server is running
        self.running = False
        # collection of key->(node_id, message_id, tick, time_offset, value) state variables
        self.states = {"/BPM": (self.node_id, 0, 0, 0, [180])}
        # collection of last message_ids from other clients nodeID -> message_id
        self.last_messages = {}
        # last time we saw a client nodeID -> our_timestamp
        self.last_seen = {}
        # last tick that happened (number, time)
        self.last_tick = (0, time.time())
        # queue of non-tick messages we have sent
        self.sent_queue = []
        # kick things off with an initial connect message
        self.send("/connect")
    
    def set_state(self, address, message=[]):
        """ Try to set a particular state variable on all nodes. """
        if not address.startswith("/"):
            raise SyncjamsException("State address must start with '/'.")
        self._send("/state" + address, [self.last_tick[0], time.time() - self.last_tick[1]] + (type(message) == list and message or [message]))
    
    def get_state(self, address):
        state = self.states.get(address, (None, None, None, None, None))[-1]
        return len(state) == 1 and state[0] or state
    
    def send(self, address, value=[]):
        """ Broadcast an arbitrary message to all nodes. """
        self._send(address, value)
    
    def poll(self):
        """ Run the SyncJams inner loop once, processing network messages etc. """
        for s in self.listeners:
            s.handle_request()
        self._process_tick()
    
    def serve_forever(self):
        """ Set up a loop running the poll() forever. Good to call inside a Thread. """
        self.running = True
        while self.running:
            self.poll()
            time.sleep(0.001)
    
    def close(self):
        """ Shut down the server and quit the serve_forever() loop, if running. """
        self.running = False
        [s.close() for s in self.listeners]
        self.sender.close()
    
    ### Methods to override. ###
    
    def tick(self, tick, time):
        pass
    
    def message(self, node_id, address, *args):
        pass
    
    def state(self, node_id, address, *args):
        pass
    
    ### Private methods. ###
    
    def _process_tick(self):
        last_tick = self.last_tick[1]
        now = time.time()
        # while our metronome is behind, catch it up
        while self.last_tick[1] + self._tick_length() < now:
            # calculate new tick position and time
            self.last_tick = (self.last_tick[0] + 1, self.last_tick[1] + self._tick_length())
            # register the current new tick so we can run code
            self.tick(*self.last_tick)
        # if the tick changed then broadcast the tick we think we are up to
        if last_tick != self.last_tick[1]:
            self._broadcast_tick()
            # every tick forget about any nodes we haven't seen in a while
            self._forget_old_nodes(now)
    
    def _forget_old_nodes(self, now):
            # find nodes we have not hear from for more than timeout
            forget = [n for n in self.last_seen if (self.last_seen[n] + NODE_TIMEOUT < now)]
            if self.debug and forget:
                print "forgetting:", forget
            # remove references to those nodes
            for n in forget:
                del self.last_seen[n]
                if self.last_messages.has_key(n):
                    del self.last_messages[n]
    
    def _broadcast_tick(self):
        # broadcast what we think the current tick is to the network - and also our last known message IDs from peers
        self._send_one_to_all("/tick", [self.node_id, self.last_tick[0]] + sum([[m, self.last_messages[m]] for m in self.last_messages], []))
    
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
        if type(message) == list:
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
        if self.debug:
             print "raw packet", addr, packet
        
        # make a copy of the incoming data packet for later
        packet_copy = packet[:]
        
        # bail if incoming packets are not addressed to our top level namespace
        if not addr.startswith(self.namespace):
            self.drop("Bad namespace", addr, tags, packet_copy, source)
            return
        
        # every message should contain the other client's id
        node_id = self._parse_number_slot(packet)
        # bail if there wasn't a valid client id
        if not node_id:
            self._drop("No node_id", addr, tags, packet_copy, source)
            return
        
        # record when we last saw this particular node
        self.last_seen[node_id] = time.time()
        
        # digestible format for our address routing
        route = addr[len(self.namespace) + 1:].split("/")
        
        # consensus metronome sync message
        if len(route) and route[0] == "tick":
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
            # check if we found our id and pull out their last message id from us too
            found = [[packet[x*2], packet[x*2+1]] for x in range(len(packet) / 2) if packet[x*2] == self.node_id]
            for f in found:
                    # send through the messages that they are missing message_id, address, message
                    [self._send_one_to_all(m[1], m[2]) for m in self.sent_queue if m[0] > f[1]]
            if not len(found):
                    # send through our last message plus the entire state
                    if self.sent_queue:
                        self._send_one_to_all(*(self.sent_queue[-1][1:]))
                    # state flood to update them
                    [self._send_one_to_all("/state" + s, self.states[s]) for s in self.states]
        # state or message packet
        else:
            # every message should contain a message id
            message_id = self._parse_number_slot(packet)
            # if this is the next in the sequence from this client then increment that counter
            if not ((self.last_messages.get(node_id, None) is None) or (message_id == self.last_messages[node_id] + 1)):
                self._drop("Old message", addr, tags, packet_copy, source)
            else:
                # log that we have received latest message from this client
                self.last_messages[node_id] = message_id
                # received state update message
                if len(route) and route[0] == "state":
                    tick = self._parse_number_slot(packet)
                    timediff = self._parse_number_slot(packet, coorce=float)
                    key = "/" + "/".join(route[1:])
                    # tick, time_offset, value
                    if not self.states.has_key(key) or self.states[key][2] < tick or (self.states[key][2] == tick and self.states[key][3] < timediff):
                        self.states[key] = (node_id, message_id, tick, timediff, packet)
                        # run the state change callback
                        self.state(node_id, key, *packet)
                # received regular broadcast message from a node
                else:
                    # run the message callback
                    self.message(node_id, "/" + "/".join(route), *packet)
    
    def _send_one_to_all(self, address, message):
        # set up the new OSC message to be sent out
        oscmsg = OSC.OSCMessage()
        oscmsg.setAddress(self.namespace + address)
        # add the message parts to it
        [oscmsg.append(m) for m in message]
        # send one message out to all broadcast/multicast networks possible, ignoring errors
        for a in ADDRESSES:
            try:
                return self.sender.sendto(oscmsg, (ADDRESSES[a], self.port))
            except OSCClientError, e:
                # silently drop socket errors because we'll just keep trying
                # TODO: log
                print "Dropped message send:", oscmsg
                print e
    
    ### Utility methods. ###
    
    def _tick_length(self):
        try:
            bpm = float(self.states["/BPM"][-1][0])
        except ValueError:
            bpm = 180
        except IndexError:
            bpm = 180
        return 60.0 / bpm
    
    def _parse_number_slot(self, packet, idx=0, coorce=int):
        try:
            return coorce(packet.pop(idx))
        except ValueError:
            pass
        except IndexError:
            pass
    
    def _drop(self, message, addr, tags, packet, source, route=None):
        if self.debug:
            print "DROPPED (%s) from %s" % (message, OSC.getUrlStr(source))
            print "\taddr:", addr
            print "\ttypetags:", tags
            print "\tdata:", packet
            if route:
                print "\troute:", route
    
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
    
    # Start a test syncjams instance
    s = TestSyncjamsNode(debug=len(sys.argv) > 1)
    print "Starting SyncJams node ID =", s.node_id
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

