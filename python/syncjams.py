#!/usr/bin/env python

import OSC
import socket
from random import randint

PORT = 23232

ANY = '0.0.0.0'
ADDRESSES = {
	"broadcast": '255.255.255.255',
	"multicast": '239.255.232.32'
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
		self.sender = OSC.OSCClient(*args, **kwargs)
		self.sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.sender.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		# self.sender.connect((ANY, port))
		self.sender.socket.bind((ANY, port))
		self.sender.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
	
	def sendto(self, oscmsg, address):
		return self.sender.sendto(oscmsg, address)
	
	def close(self):
		self.sender.close()

class SyncjamsNode:
	def __init__(self, *args, **kwargs):
		self.DEBUG = kwargs.has_key("debug") and kwargs.pop("debug")
		self.port = kwargs.has_key("port") and kwargs.pop("port") or PORT
		# server and client 
		# self.listeners = [SyncjamsListener(ADDRESSES["broadcast"], self.port, callback=self.osc_message_handler), SyncjamsListener(ADDRESSES["multicast"], self.port, callback=self.osc_message_handler)]
		self.listeners = [SyncjamsListener(ADDRESSES["multicast"], self.port, callback=self.osc_message_handler)]
		self.sender = SyncjamsSender(self.port)
		# randomly chosen client ID
		self.client_id = randint(0, pow(2, 32))
		# whether or not the server is running
		self.running = False
	
	# define a message-handler function for the server to call.
	def osc_message_handler(self, addr, tags, stuff, source):
		# make sure the incoming packets are always of the 
		if addr.startswith(NAMESPACE):
			if self.DEBUG:
				print "received new osc msg from %s" % OSC.getUrlStr(source)
				print "with addr : %s" % addr
				print "typetags %s" % tags
				print "data %s" % stuff
				print "---"
	
	def send(self, address, message=[]):
		oscmsg = OSC.OSCMessage()
		if address.startswith("/"):
			oscmsg.setAddress(NAMESPACE + address)
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
	# Start a test syncjams instance
	s = SyncjamsNode(debug=True)
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

