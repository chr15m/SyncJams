#!/usr/bin/env python

import OSC
import socket
import time
from random import randint

PORT = 23232

ANY = '0.0.0.0'
ADDRESSES = {
	"broadcast": '255.255.255.255',
	# "multicast": '239.255.232.32',
	"android": '192.168.42.255',
}

NAMESPACE = "/syncjams"

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

class SyncjamsNode:
	# map of known ClientIDs with information on messages send and received to/from them
	# format:
	# ClientID -> last_message_received_time, last_received_message_id, last_our_message_acknowledged_id
	client_map = {}
	
	def __init__(self, handler, latency=0, *args, **kwargs):
		self.DEBUG = kwargs.has_key("debug") and kwargs.pop("debug")
		self.port = kwargs.has_key("port") and kwargs.pop("port") or PORT
		# set up servers to listen on each broadcast address we want to listen on
		# self.listeners = [SyncjamsListener(ADDRESSES["multicast"], self.port, callback=self.osc_message_handler)]
		self.listeners = [SyncjamsListener(ADDRESSES["broadcast"], self.port, callback=self.osc_message_handler)]
		# set up an osc sender to send out broadcast messages
		self.sender = self.make_sender()
		# randomly chosen client ID
		self.client_id = randint(0, pow(2, 30))
		# increment a message id every time we send
		self.message_id = 0
		# whether or not the server is running
		self.running = False
	
	def make_sender(self):
		# OSCClient that sends with broadcast flags on from any assigned port
		sender = OSC.OSCClient()
		sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		sender.socket.bind((ANY, 0))
		sender.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
		return sender
	
	def parse_id_slot(self, packet, idx):
		try:
			return int(packet.pop(idx))
		except ValueError:
			pass
		except IndexError:
			pass
	
	def drop(self, message, addr, tags, packet, source, route=None):
		if self.DEBUG:
			print "DROPPED (%s) from %s" % (message, OSC.getUrlStr(source))
			print "\taddr:", addr
			print "\ttypetags:", tags
			print "\tdata:", packet
			if route:
				print "\troute:", route
	
	# define a message-handler function for the server to call.
	def osc_message_handler(self, addr, tags, packet, source):
		# make a copy of the incoming data packet for later
		packet_copy = packet[:]
		
		# bail if incoming packets are not addressed to our top level namespace
		if not addr.startswith(NAMESPACE):
			self.drop("Bad namespace", addr, tags, packet_copy, source)
			return
		
		# every message should contain the other client's id
		client_id = self.parse_id_slot(packet, 0)
		# bail if there wasn't a valid client id
		if not client_id:
			self.drop("No client_id", addr, tags, packet_copy, source)
			return
		
		# digestible format for our address routing
		route = addr[len(NAMESPACE) + 1:].split("/")
		# every message should contain a message id
		message_id = self.parse_id_slot(packet, 0)
		# ensure there is a valid client map for this client
		self.client_map[client_id] = self.client_map.get(client_id, [None, None, None])
		# shortcut reference to a particular client's map
		client = self.client_map[client_id]
		# always set the last_message_received_time for any client we ever hear from
		client[0] = time.time()
		
		# if this is a special ACK message for one of my sent
		if len(route) and route[0] == "ACK":
			# grab the id of the client this was destined for
			dest_client_id = self.parse_id_slot(packet, 0)
			# make sure ack is destined for me and make sure it's an unseen ack
			if dest_client_id == self.client_id and (client[2] is None or message_id > client[2]):
				# add the last_our_message_acknowledged_id to this client's map
				client[2] = message_id
				# print "ACK", client_id, message_id
		elif len(route) and route[0] == "metronome":
			# special consensus metronome sync message
			pass
		elif len(route) and route[0] == "state":
			# special state-variable message -> key=address value=message
			pass
		else:
			# ack every message received
			self.send("/ACK", [client_id], message_id=message_id)
			# if this is the next in the sequence from this client then increment that counter
			if client[1] is None or message_id == client[1] + 1:
				client[1] = message_id
				if self.DEBUG:
					print "received from %s" % OSC.getUrlStr(source)
					print "\troute:", route
					print "\tdata:", packet
			else:
				self.drop("Old message", addr, tags, packet_copy, source)
	
	def send(self, address, message=[], message_id=None):
		if not address.startswith("/"):
			raise SyncjamsException("Address must start with '/'.")
		# message_id increments for every message
		if message_id is None:
			self.message_id += 1
			message_id = self.message_id
		# set up the new OSC message to be sent out
		oscmsg = OSC.OSCMessage()
		oscmsg.setAddress(NAMESPACE + address)
		# add the default syncjams parameters - client_id and message_id
		oscmsg.append(self.client_id)
		oscmsg.append(message_id)
		# add whatever other data the user wants to send
		if type(message) == list:
			for m in message:
				oscmsg.append(m)
		else:
			oscmsg.append(message)
		# send the message out to all broadcast/multicast networks possible
		for a in ADDRESSES:
			try:
				return self.sender.sendto(oscmsg, (ADDRESSES[a], self.port))
			except OSCClientError:
				pass
				# silently drop socket errors because we'll just keep trying
	
	def poll(self):
		""" Run the SyncJams inner loop once, processing network messages etc. """
		for s in self.listeners:
			s.handle_request()
	
	def serve_forever(self):
		while self.running:
			self.poll()
			time.sleep(0.001)
	
	def close(self):
		self.running = False
		[s.close() for s in self.listeners]
		self.sender.close()

# Test code for running an interactive version that prints results
if __name__ == "__main__":
	# setup handler for receiving message from syncjams network
	class TestNetsyncHandler:
		def receive(route, message):
			print "Test received:", route, message
	
	# Start a test syncjams instance
	s = SyncjamsNode(debug=True, handler=TestNetsyncHandler())
	print "Starting SyncJams node."
	from threading import Thread
	st = Thread( target = s.serve_forever )
	st.start()
	
	banner = """SyncjamsNode is 's'. Send with `s.send('/myaddress/test', [1, 2, 3, "hello"])`"""
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

