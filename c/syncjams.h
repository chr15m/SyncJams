/**
 * Copyright (c) 2015, Chris McCormick <chris@mccormick.cx>
 */

#ifndef _SYNCJAMS_
#define _SYNCJAMS_

#include "tinyosc/tinyosc.h"

#include <arpa/inet.h>
#include <sys/select.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <unistd.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct _syncjams
{    
    int l_sock;         /* socket id */
} syncjams;

syncjams* syncjams_setup();

void syncjams_poll(syncjams *instance, float f_delta_ms);

void syncjams_send(syncjams *instance);

void syncjams_destroy(syncjams *instance);

#ifdef __cplusplus
}
#endif

#endif // _SYNCJAMS_
