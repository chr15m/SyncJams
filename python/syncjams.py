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

class SyncjamsListener(OSC.OSCServer):
	client = None
	def __init__(self, address, port, callback, *args, **kwargs):
		self.multicast = address.startswith("239.255") or address.startswith("224.")
		self.address = address
		OSC.OSCServer.__init__(self, (self.multicast and ANY or address, port), *args, **kwargs)
		# listen for incoming syncjams osc messages and send to main callback
		self.addMsgHandler("default", callback)
	
	def server_bind(self):
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		# SO_REUSEPORT on BSD
		if 'SO_REUSEPORT' in vars(socket):
			self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
		result = OSC.OSCServer.server_bind(self)
		self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
		if self.multicast:
			self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(self.address) + socket.inet_aton(ANY))
		return result

class SyncjamsSender():
	def __init__(self, port, *args, **kwargs):
		# Sends with broadcast flags on from any assigned port
		self.sender = OSC.OSCClient(*args, **kwargs)
		self.sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		self.sender.socket.bind((ANY, 0))
		self.sender.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
	
	def sendto(self, oscmsg, address):
		return self.sender.sendto(oscmsg, address)
	
	def close(self):
		self.sender.close()

class SyncjamsNode:
	# map of known ClientIDs with information on messages send and received to/from them
	# format:
	# ClientID -> last_message_received_time, last_received_message_id, last_our_message_acknowledged_id
	client_map = {}
	
	def __init__(self, handler, latency=0, *args, **kwargs):
		self.DEBUG = kwargs.has_key("debug") and kwargs.pop("debug")
		self.port = kwargs.has_key("port") and kwargs.pop("port") or PORT
		# self.listeners = [SyncjamsListener(ADDRESSES["broadcast"], self.port, callback=self.osc_message_handler), SyncjamsListener(ADDRESSES["multicast"], self.port, callback=self.osc_message_handler)]
		# self.listeners = [SyncjamsListener(ADDRESSES["multicast"], self.port, callback=self.osc_message_handler)]
		self.listeners = [SyncjamsListener(ADDRESSES["broadcast"], self.port, callback=self.osc_message_handler)]
		self.sender = SyncjamsSender(self.port)
		# randomly chosen client ID
		self.client_id = randint(0, pow(2, 30))
		# increment a message id every time we send
		self.message_id = 0
		# whether or not the server is running
		self.running = False
	
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
		packet_copy = packet[:]
		# make sure the incoming packets are always addressed to our top level namespace
		if addr.startswith(NAMESPACE):
			# digestible format for our address routing
			route = addr[len(NAMESPACE) + 1:].split("/")
			# every message should contain the other client's id
			client_id = self.parse_id_slot(packet, 0)
			# every message should contain a message id
			message_id = self.parse_id_slot(packet, 0)
			# proceed if there was a valid client id
			if client_id:
				# make sure there is a client map for this client
				self.client_map[client_id] = self.client_map.get(client_id, [None, None, None])
				client = self.client_map[client_id]
				# set the last_message_received_time for any client we ever hear from
				client[0] = time.time()
				# if this is a special ACK message
				if len(route) and route[0] == "ACK":
					dest_client_id = self.parse_id_slot(packet, 0)
					# make sure ack is destined for me and
					# ignore my own acks and ignore old message_ids for this client
					if dest_client_id and dest_client_id == self.client_id and (client[2] is None or message_id > client[2]):
						# add the last_our_message_acknowledged_id to this client's map
						# print "ACK", client_id, message_id
						client[2] = message_id
				elif len(route) and route[0] == "metronome":
					# special consensus metronome sync message
					pass
				elif len(route) and route[0] == "state":
					# special state-variable message -> key=address value=message
					pass
				else:
					# ack every message received that wasn't from me
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
			else:
				self.drop("No client_id", addr, tags, packet_copy, source)
		else:
			self.drop("Missing ids", addr, tags, packet_copy, source)
	
	def send(self, address, message=[], message_id=None):
		if address.startswith("/"):
			if message_id is None:
				self.message_id += 1
				message_id = self.message_id
			oscmsg = OSC.OSCMessage()
			oscmsg.setAddress(NAMESPACE + address)
			oscmsg.append(self.client_id)
			oscmsg.append(message_id)
			if type(message) == list:
				for m in message:
					oscmsg.append(m)
			else:
				oscmsg.append(message)
			# make all of the senders send
			[self.sender.sendto(oscmsg, (ADDRESSES[a], self.port)) for a in ADDRESSES]
		else:
			raise SyncjamsException("Address must start with '/'.")
	
	def serve_forever(self):
		"""Handle one request at a time until server is closed."""
		self.running = True
		while self.running:
			[s.handle_request() for s in self.listeners]
	
	def close(self):
		self.running = False
		[s.close() for s in self.listeners]
		self.sender.close()

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
		from IPython.frontend.terminal.embed import InteractiveShellEmbed
		InteractiveShellEmbed(banner1=banner)()
	except ImportError:
		import code
		code.InteractiveConsole(locals=globals()).interact(banner)
	
	print "Shutting down SyncJams node."
	s.close()
	print "Waiting for thread to finish."
	st.join()
	print "Done."

