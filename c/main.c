/**
 * Copyright (c) 2015, Chris McCormick <chris@mccormick.cx>
 */

#include "syncjams.h"

#include <signal.h>
#include <unistd.h>

static volatile bool keepRunning = true;

// handle Ctrl+C
static void sigintHandler(int x) {
  keepRunning = false;
}

int main(int argc, char *argv[]) {
  syncjams s;
  
  // register the SIGINT handler (Ctrl+C)
  signal(SIGINT, &sigintHandler);
  
  syncjams_setup(&s);
  
  printf("SyncJams setup complete.\n");
  printf("Listening on port 23232.\n");
  printf("Press Ctrl+C to exit.\n");
  
  while (keepRunning) {
    // 64 frames per block
    // 44100 samples per second
    // 1000 ms per second
    // 1000 * (64.0 / 44100) = 1.4512471655328798
    printf("Polling.\n");
    syncjams_poll(&s, 1.4512471655328798);
    // normally we would run this as fast as the blocks from from audio
    // sleeping a whole second here instead for test purposes.
    sleep(1);
  }
  
  printf("Exiting.\n");
  
  syncjams_destroy(&s);
  
  return 0;
}
