#!/usr/bin/env python

# PEP8 all up in here:
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4 smartindent

from threading import Thread
from syncjams import SyncjamsListener

def user_callback(path, tags, args, source):
    print source
    print "\t", path, tags, args

server = SyncjamsListener("0.0.0.0", 23232, user_callback)
server.serve_forever()
