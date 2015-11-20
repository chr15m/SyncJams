/**
 * Copyright (c) 2015, Chris McCormick <chris@mccormick.cx>
 * 
 * This code was originally derived from tinyosc/main.c by Martin Roth.
 *
 * He gave me permission to re-license this code.
 *
 */

#include "syncjams.h"

syncjams* syncjams_setup(syncjams *instance) {
  int port=23232;
  int optval = 1; // all our flags are true
  
  // open a socket to listen for UDP packets
  instance->l_sock = socket(AF_INET, SOCK_DGRAM, 0);
  fcntl(instance->l_sock, F_SETFL, O_NONBLOCK); // set the socket to non-blocking
  
  // set socket flags friendly for multiple instances of SyncJams
  setsockopt(instance->l_sock, SOL_SOCKET, SO_REUSEADDR, &optval, sizeof optval);
  // Linux doesn't do this flag
  #ifdef SO_REUSEPORT
  setsockopt(instance->l_sock, SOL_SOCKET, SO_REUSEPORT, &optval, sizeof optval);
  #endif
  setsockopt(instance->l_sock, SOL_SOCKET, SO_BROADCAST, &optval, sizeof optval);
  
  // bind the socket
  struct sockaddr_in sin;
  sin.sin_family = AF_INET;
  sin.sin_port = htons(port);
  sin.sin_addr.s_addr = INADDR_ANY;
  bind(instance->l_sock, (struct sockaddr *) &sin, sizeof(struct sockaddr_in));
}

void syncjams_poll(syncjams *instance, float f_delta_ms) {
  char buffer[2048]; // declare a 2Kb buffer to read packet data into
  fd_set readSet;
  FD_ZERO(&readSet);
  FD_SET(instance->l_sock, &readSet);
  struct timeval timeout = {0, 0}; // select times out after 1 second
  if (select(instance->l_sock+1, &readSet, NULL, NULL, &timeout) > 0) {
    struct sockaddr sa; // can be safely cast to sockaddr_in
    socklen_t sa_len = sizeof(struct sockaddr_in);
    int len = 0;
    while ((len = (int) recvfrom(instance->l_sock, buffer, sizeof(buffer), 0, &sa, &sa_len)) > 0) {
      tosc_printOscBuffer(buffer, len);
    }
  }
}

void syncjams_send(syncjams *instance) {
  char buffer[2048]; // declare a 2Kb buffer to read packet data into
  int len = 0;
  char blob[8] = {0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF};
  len = tosc_write(buffer, sizeof(buffer), "/address", "fsibTFNI",
      1.0f, "hello world", -1, sizeof(blob), blob);
  tosc_printOscBuffer(buffer, len);
  // TODO: actually send to the network
}

void syncjams_destroy(syncjams *instance) {
  // close the UDP socket
  close(instance->l_sock);
}
